from __future__ import annotations

import json
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from xml.sax.saxutils import escape

from src.core.config import TMP_DIR
from src.modules.storage.archive_storage_info import ArchiveStorageInfoResolver, resolve_article_archive_candidate_dirs
from src.modules.storage.sqlite_store import SQLiteStore
from src.modules.utils.file_utils import clean_path_part


EXCEL_HEADERS = [
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
]

DETAIL_METRIC_KEYS = [
    "audience_count",
    "read_count",
    "like_count",
    "share_count",
    "recommend_count",
    "comment_count",
]


@dataclass(frozen=True)
class ArchiveExcelExportFile:
    account_id: int
    account_name: str
    row_count: int
    temp_path: Path
    output_path: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "accountId": self.account_id,
            "accountName": self.account_name,
            "rowCount": self.row_count,
            "tempPath": str(self.temp_path),
            "outputPath": str(self.output_path),
            "fileName": self.output_path.name,
        }


@dataclass
class ArchiveExcelExportResult:
    ok: bool
    status: str
    files: list[ArchiveExcelExportFile] = field(default_factory=list)
    missing_account_ids: list[int] = field(default_factory=list)
    message: str = ""

    @property
    def exported_file_count(self) -> int:
        return len(self.files)

    @property
    def total_row_count(self) -> int:
        return sum(file.row_count for file in self.files)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "exportedFileCount": self.exported_file_count,
            "totalRowCount": self.total_row_count,
            "files": [file.to_dict() for file in self.files],
            "missingAccountIds": self.missing_account_ids,
            "message": self.message,
        }


class ArchiveExcelExportService:
    """把 SQLite 文章索引和本地 article_detail.json 汇总导出为 Excel。"""

    def __init__(
        self,
        *,
        store: SQLiteStore,
        storage_root: str | Path,
        temp_root: str | Path = TMP_DIR,
    ) -> None:
        self.store = store
        self.storage_root = Path(storage_root)
        self.temp_root = Path(temp_root)
        self.archive_resolver = ArchiveStorageInfoResolver(self.storage_root)

    def export_accounts(self, account_ids: Iterable[int], target_dir: str | Path) -> ArchiveExcelExportResult:
        safe_account_ids = _unique_positive_ids(account_ids)
        if not safe_account_ids:
            return ArchiveExcelExportResult(ok=False, status="empty", message="请先选择要导出的公众号。")

        if not str(target_dir or "").strip():
            return ArchiveExcelExportResult(ok=False, status="missing-target-dir", message="请先选择 Excel 保存目录。")

        target_path = Path(target_dir)
        target_path.mkdir(parents=True, exist_ok=True)
        run_dir = self._create_temp_run_dir()
        account_rows = {int(row["id"]): row for row in self.store.list_public_accounts()}
        files: list[ArchiveExcelExportFile] = []
        missing_account_ids: list[int] = []
        used_names: set[str] = set()

        for account_id in safe_account_ids:
            account = account_rows.get(account_id)
            if account is None:
                missing_account_ids.append(account_id)
                continue

            articles = self.store.list_public_articles_for_export(account_id)
            account_name = str(account.get("account_name") or "")
            rows = self._build_excel_rows(articles)
            filename = _build_export_filename(
                account_name=account_name,
                row_count=len(articles),
                used_names=used_names,
            )
            temp_path = run_dir / filename
            output_path = _unique_output_path(target_path / filename)
            write_xlsx(temp_path, [EXCEL_HEADERS, *rows])
            shutil.copy2(temp_path, output_path)
            files.append(
                ArchiveExcelExportFile(
                    account_id=account_id,
                    account_name=account_name,
                    row_count=len(articles),
                    temp_path=temp_path,
                    output_path=output_path,
                )
            )

        ok = bool(files) and not missing_account_ids
        status = "ok" if ok else "partial-failed" if files else "failed"
        message = f"已导出 {len(files)} 个 Excel 文件。"
        if missing_account_ids:
            message += f" 有 {len(missing_account_ids)} 个公众号记录不存在。"
        return ArchiveExcelExportResult(
            ok=bool(files),
            status=status,
            files=files,
            missing_account_ids=missing_account_ids,
            message=message,
        )

    def _create_temp_run_dir(self) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        run_dir = self.temp_root / f"archive_excel_export_{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def _build_excel_rows(self, articles: list[dict[str, Any]]) -> list[list[str]]:
        rows: list[list[str]] = []
        for index, article in enumerate(articles, start=1):
            rows.append(self._build_excel_row(index, article))
        return rows

    def _build_excel_row(self, index: int, article: dict[str, Any]) -> list[str]:
        collect_status = str(article.get("collect_status") or "")
        detail: dict[str, Any] = {}
        record_status = "采集失败"

        if collect_status == "saved":
            detail_path = self._resolve_detail_path(article)
            if detail_path is None:
                record_status = "未找到本地归档目录"
            elif not detail_path.exists():
                record_status = "缺少 article_detail.json"
            else:
                detail = _read_json_object(detail_path)
                record_status = "保存成功" if detail else "article_detail.json 读取失败"

        short_link = _first_text(detail.get("short_link"), detail.get("article_link"), article.get("article_link"))
        metric_values = [_format_excel_value(detail.get(key)) for key in DETAIL_METRIC_KEYS] if detail else [""] * 6

        return [
            str(index),
            record_status,
            _format_excel_value(article.get("published_article_time")),
            _format_excel_value(article.get("article_title")),
            short_link,
            *metric_values,
            _format_excel_value(article.get("collect_time")),
        ]

    def _resolve_detail_path(self, article: dict[str, Any]) -> Path | None:
        archive_info = self.archive_resolver.resolve_for_row(article)
        if archive_info.archive_dir:
            return archive_info.archive_dir / "article_detail.json"

        candidates = resolve_article_archive_candidate_dirs(
            storage_root=self.storage_root,
            account_name=str(article.get("account_name") or ""),
            published_article_time=str(article.get("published_article_time") or ""),
            article_title=str(article.get("article_title") or ""),
        )
        if not candidates:
            return None
        return candidates[0] / "article_detail.json"


def write_xlsx(path: str | Path, rows: list[list[Any]]) -> Path:
    """使用 OOXML 最小结构写出 .xlsx，避免导出功能绑定额外第三方库。"""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet_xml = _build_sheet_xml(rows)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES_XML)
        archive.writestr("_rels/.rels", _ROOT_RELS_XML)
        archive.writestr("xl/workbook.xml", _WORKBOOK_XML)
        archive.writestr("xl/_rels/workbook.xml.rels", _WORKBOOK_RELS_XML)
        archive.writestr("xl/styles.xml", _STYLES_XML)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return output_path


def _build_sheet_xml(rows: list[list[Any]]) -> str:
    row_xml = []
    max_col_count = max((len(row) for row in rows), default=1)
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            cell_ref = f"{_column_name(col_index)}{row_index}"
            safe_value = escape(_format_excel_value(value))
            cells.append(f'<c r="{cell_ref}" t="inlineStr"><is><t>{safe_value}</t></is></c>')
        row_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    dimension = f"A1:{_column_name(max_col_count)}{max(1, len(rows))}"
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<dimension ref="{dimension}"/>'
        '<cols>'
        '<col min="1" max="1" width="8" customWidth="1"/>'
        '<col min="2" max="2" width="22" customWidth="1"/>'
        '<col min="3" max="3" width="20" customWidth="1"/>'
        '<col min="4" max="4" width="44" customWidth="1"/>'
        '<col min="5" max="5" width="40" customWidth="1"/>'
        '<col min="6" max="11" width="12" customWidth="1"/>'
        '<col min="12" max="12" width="22" customWidth="1"/>'
        '</cols>'
        f'<sheetData>{"".join(row_xml)}</sheetData>'
        '</worksheet>'
    )


def _column_name(index: int) -> str:
    name = ""
    current = max(1, int(index))
    while current:
        current, remainder = divmod(current - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _format_excel_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    return str(value)


def _first_text(*values: Any) -> str:
    for value in values:
        text = _format_excel_value(value).strip()
        if text:
            return text
    return ""


def _build_export_filename(*, account_name: str, row_count: int, used_names: set[str]) -> str:
    safe_account_name = clean_path_part(account_name or "未知公众号", max_length=64)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"{safe_account_name}_文章记录_{max(0, int(row_count))}篇_{timestamp}"
    candidate = base_name
    suffix = 1
    while f"{candidate}.xlsx" in used_names:
        candidate = f"{base_name}_{suffix}"
        suffix += 1
    filename = f"{candidate}.xlsx"
    used_names.add(filename)
    return filename


def _unique_output_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    index = 1
    while True:
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def _unique_positive_ids(values: Iterable[int]) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()
    for value in values:
        try:
            item = int(value)
        except (TypeError, ValueError):
            continue
        if item <= 0 or item in seen:
            continue
        seen.add(item)
        ids.append(item)
    return ids


_CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

_ROOT_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

_WORKBOOK_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="文章记录" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>"""

_WORKBOOK_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

_STYLES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="1"><font><sz val="11"/><name val="Microsoft YaHei"/></font></fonts>
  <fills count="1"><fill><patternFill patternType="none"/></fill></fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


__all__ = [
    "ArchiveExcelExportFile",
    "ArchiveExcelExportResult",
    "ArchiveExcelExportService",
    "EXCEL_HEADERS",
    "write_xlsx",
]
