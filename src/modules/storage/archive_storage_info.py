from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from src.core.config import PROJECT_ROOT
from src.modules.utils.file_utils import clean_path_part
from src.modules.utils.time_utils import format_datetime_for_dir


@dataclass(frozen=True)
class ArchiveStorageInfo:
    """单篇文章本地归档目录及其真实磁盘占用。"""

    archive_dir: Path | None
    archive_dirs: list[Path]
    size_bytes: int
    size_label: str


class ArchiveStorageInfoResolver:
    """按文章索引定位本地归档目录，并计算目录实际占用空间。"""

    def __init__(self, storage_root: str | Path) -> None:
        self.storage_root = Path(storage_root)
        self._candidate_cache: dict[Path, list[Path]] = {}
        self._detail_link_cache: dict[Path, str | None] = {}
        self._size_cache: dict[Path, int] = {}

    def resolve_for_row(self, row: Mapping[str, object]) -> ArchiveStorageInfo:
        return self.resolve(
            account_name=str(row.get("account_name") or ""),
            published_article_time=str(row.get("published_article_time") or ""),
            article_title=str(row.get("article_title") or ""),
            article_link=str(row.get("article_link") or ""),
        )

    def resolve(
        self,
        *,
        account_name: str,
        published_article_time: str,
        article_title: str,
        article_link: str,
    ) -> ArchiveStorageInfo:
        archive_dirs = self._resolve_archive_dirs(
            account_name=account_name,
            published_article_time=published_article_time,
            article_title=article_title,
            article_link=article_link,
        )
        size_bytes = sum(self._directory_size(archive_dir) for archive_dir in archive_dirs)

        return ArchiveStorageInfo(
            archive_dir=archive_dirs[0] if archive_dirs else None,
            archive_dirs=archive_dirs,
            size_bytes=size_bytes,
            size_label=format_size_label(size_bytes),
        )

    def _resolve_archive_dirs(
        self,
        *,
        account_name: str,
        published_article_time: str,
        article_title: str,
        article_link: str,
    ) -> list[Path]:
        base_dir = build_archive_lookup_base_dir(
            storage_root=self.storage_root,
            account_name=account_name,
            published_article_time=published_article_time,
            article_title=article_title,
        )
        candidates = self._candidate_dirs(base_dir)
        if not candidates:
            return []

        target_link = _normalize_article_link(article_link)
        if target_link:
            matched = [candidate for candidate in candidates if self._detail_short_link(candidate) == target_link]
            if matched:
                return matched

        if len(candidates) == 1:
            candidate_link = self._detail_short_link(candidates[0])
            if not target_link or not candidate_link or candidate_link == target_link:
                return candidates

        return []

    def _candidate_dirs(self, base_dir: Path) -> list[Path]:
        cached = self._candidate_cache.get(base_dir)
        if cached is not None:
            return cached

        account_dir = base_dir.parent
        base_name = base_dir.name
        candidates: list[Path] = []
        if account_dir.exists():
            for child in account_dir.iterdir():
                if not child.is_dir():
                    continue
                if child.name == base_name or _is_numbered_duplicate(child.name, base_name):
                    candidates.append(child)

        candidates.sort(key=lambda path: _archive_dir_sort_key(path.name, base_name))
        self._candidate_cache[base_dir] = candidates
        return candidates

    def _detail_short_link(self, archive_dir: Path) -> str | None:
        cached = self._detail_link_cache.get(archive_dir)
        if archive_dir in self._detail_link_cache:
            return cached

        detail_path = archive_dir / "article_detail.json"
        if not detail_path.exists():
            self._detail_link_cache[archive_dir] = None
            return None

        try:
            detail = json.loads(detail_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._detail_link_cache[archive_dir] = None
            return None

        if not isinstance(detail, dict):
            self._detail_link_cache[archive_dir] = None
            return None

        link = _normalize_article_link(detail.get("short_link") or detail.get("article_link"))
        self._detail_link_cache[archive_dir] = link or None
        return link or None

    def _directory_size(self, archive_dir: Path) -> int:
        cached = self._size_cache.get(archive_dir)
        if cached is not None:
            return cached

        size = directory_size_bytes(archive_dir)
        self._size_cache[archive_dir] = size
        return size


def default_storage_root_for_db(db_path: str | Path) -> Path:
    """从数据库位置推断归档根目录，保持接口层不硬编码路径细节。"""
    path = Path(db_path)
    if path.parent.name == "data":
        return path.parent.parent / "storages"
    if path.parent == PROJECT_ROOT:
        return PROJECT_ROOT / "storages"
    return path.parent / "storages"


def resolve_article_archive_info(
    *,
    storage_root: str | Path,
    account_name: str,
    published_article_time: str,
    article_title: str,
    article_link: str,
) -> ArchiveStorageInfo:
    resolver = ArchiveStorageInfoResolver(storage_root)
    return resolver.resolve(
        account_name=account_name,
        published_article_time=published_article_time,
        article_title=article_title,
        article_link=article_link,
    )


def resolve_article_archive_candidate_dirs(
    *,
    storage_root: str | Path,
    account_name: str,
    published_article_time: str,
    article_title: str,
) -> list[Path]:
    """按目录名定位文章归档候选目录，不依赖 article_detail.json 的短链内容。"""
    base_dir = build_archive_lookup_base_dir(
        storage_root=storage_root,
        account_name=account_name,
        published_article_time=published_article_time,
        article_title=article_title,
    )
    account_dir = base_dir.parent
    base_name = base_dir.name
    candidates: list[Path] = []
    if account_dir.exists():
        for child in account_dir.iterdir():
            if not child.is_dir():
                continue
            if child.name == base_name or _is_numbered_duplicate(child.name, base_name):
                candidates.append(child)
    candidates.sort(key=lambda path: _archive_dir_sort_key(path.name, base_name))
    return candidates


def build_archive_lookup_base_dir(
    *,
    storage_root: str | Path,
    account_name: str,
    published_article_time: str,
    article_title: str,
) -> Path:
    account_dir_name = clean_path_part(account_name or "未知公众号")
    time_part = format_datetime_for_dir(published_article_time)
    title_part = clean_path_part(article_title or "无标题文章")
    return Path(storage_root) / account_dir_name / f"{time_part} {title_part}".strip()


def directory_size_bytes(directory: str | Path) -> int:
    """递归统计目录中文件大小；忽略无法访问的文件，避免页面查询被单个文件阻塞。"""
    root = Path(directory)
    if not root.exists():
        return 0

    total = 0
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def format_size_label(size_bytes: int) -> str:
    size = max(0, int(size_bytes or 0))
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(size)
    unit_index = 0
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1

    if unit_index == 0:
        return f"{size} B"
    if value >= 100:
        return f"{value:.0f} {units[unit_index]}"
    if value >= 10:
        return f"{value:.1f} {units[unit_index]}"
    return f"{value:.2f} {units[unit_index]}"


def _is_numbered_duplicate(name: str, base_name: str) -> bool:
    if not name.startswith(f"{base_name}_"):
        return False
    suffix = name[len(base_name) + 1 :]
    return suffix.isdigit()


def _archive_dir_sort_key(name: str, base_name: str) -> tuple[int, int, str]:
    if name == base_name:
        return (0, 0, name)
    suffix = name[len(base_name) + 1 :] if _is_numbered_duplicate(name, base_name) else ""
    return (1, int(suffix or 0), name)


def _normalize_article_link(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    parsed = urlparse(text)
    if parsed.scheme and parsed.netloc and parsed.path:
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path}".rstrip("/")
    return text.rstrip("/")


__all__ = [
    "ArchiveStorageInfo",
    "ArchiveStorageInfoResolver",
    "build_archive_lookup_base_dir",
    "default_storage_root_for_db",
    "directory_size_bytes",
    "format_size_label",
    "resolve_article_archive_info",
    "resolve_article_archive_candidate_dirs",
]
