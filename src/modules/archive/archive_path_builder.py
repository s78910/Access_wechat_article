from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


WINDOWS_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
TEMPORARY_QUERY_KEYS = {
    "key",
    "pass_ticket",
    "appmsg_token",
    "scene",
    "subscene",
    "clicktime",
    "enterid",
    "from",
    "isappinstalled",
}


@dataclass(frozen=True, slots=True)
class ArchivePath:
    article_key: str
    article_directory: Path
    relative_archive_dir: str


def normalize_account_name(account_name: str) -> str:
    normalized = unicodedata.normalize("NFC", account_name)
    return " ".join(normalized.split())


def sanitize_windows_segment(value: str, *, max_length: int = 80) -> str:
    """清洗 Windows 路径段，并处理保留设备名。"""
    normalized = unicodedata.normalize("NFC", value).strip()
    cleaned = WINDOWS_INVALID_CHARS.sub("_", normalized).rstrip(" .")
    if not cleaned or not cleaned.strip("."):
        cleaned = "未命名"
    stem = cleaned.split(".", 1)[0].upper()
    if stem in WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned[:max_length].rstrip(" .") or "未命名"


def canonicalize_article_link(article_link: str) -> str:
    """移除临时参数并稳定查询参数顺序，供文章身份哈希使用。"""
    parsed = urlsplit(article_link.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("article_link 必须是有效的 HTTP/HTTPS URL")

    host = parsed.hostname.lower()
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    query_items = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TEMPORARY_QUERY_KEYS
    ]
    query_items.sort(key=lambda item: (item[0], item[1]))
    return urlunsplit(
        (
            parsed.scheme.lower(),
            host,
            parsed.path or "/",
            urlencode(query_items, doseq=True),
            "",
        )
    )


class ArchivePathBuilder:
    def __init__(self, storage_root: str | Path) -> None:
        self.storage_root = Path(storage_root).resolve()

    def build(
        self,
        *,
        account_name: str,
        article_title: str,
        published_article_time: str,
        article_link: str,
        existing_archive_dir: str = "",
    ) -> ArchivePath:
        normalized_account_name = normalize_account_name(account_name)
        if not normalized_account_name:
            raise ValueError("account_name 不能为空")
        canonical_link = canonicalize_article_link(article_link)
        article_key = hashlib.sha256(
            f"{normalized_account_name}\n{canonical_link}".encode("utf-8")
        ).hexdigest()[:12]

        if existing_archive_dir.strip():
            relative = Path(existing_archive_dir.strip())
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("existing_archive_dir 必须位于 storages 内")
            article_directory = (self.storage_root / relative).resolve()
            if not article_directory.is_relative_to(self.storage_root):
                raise ValueError("existing_archive_dir 必须位于 storages 内")
            return ArchivePath(
                article_key=article_key,
                article_directory=article_directory,
                relative_archive_dir=article_directory.relative_to(self.storage_root).as_posix(),
            )

        try:
            published_at = datetime.strptime(published_article_time.strip(), "%Y-%m-%d %H:%M")
        except ValueError as exc:
            raise ValueError("published_article_time 必须是 YYYY-MM-DD HH:MM") from exc

        account_segment = sanitize_windows_segment(normalized_account_name)
        title_segment = sanitize_windows_segment(article_title)
        directory_name = (
            f"{published_at.strftime('%Y-%m-%d %H-%M')} "
            f"{title_segment}__{article_key}"
        )
        article_directory = self.storage_root / account_segment / directory_name
        return ArchivePath(
            article_key=article_key,
            article_directory=article_directory,
            relative_archive_dir=article_directory.relative_to(self.storage_root).as_posix(),
        )
