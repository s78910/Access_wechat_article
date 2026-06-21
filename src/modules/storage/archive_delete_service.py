from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from src.modules.storage.archive_storage_info import ArchiveStorageInfoResolver
from src.modules.storage.sqlite_store import SQLiteStore


@dataclass
class ArchiveDeleteFailure:
    """记录本地归档目录删除失败的路径和原因，便于前端提示和后续排查。"""

    path: str
    error: str


@dataclass
class ArchiveDeleteResult:
    """数据档案删除操作的统一返回结构。"""

    deleted_article_count: int = 0
    deleted_account_count: int = 0
    deleted_archive_dir_count: int = 0
    missing_article_ids: list[int] = field(default_factory=list)
    failures: list[ArchiveDeleteFailure] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures

    def merge(self, other: "ArchiveDeleteResult") -> None:
        self.deleted_article_count += other.deleted_article_count
        self.deleted_account_count += other.deleted_account_count
        self.deleted_archive_dir_count += other.deleted_archive_dir_count
        self.missing_article_ids.extend(other.missing_article_ids)
        self.failures.extend(other.failures)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "deletedArticleCount": self.deleted_article_count,
            "deletedAccountCount": self.deleted_account_count,
            "deletedArchiveDirCount": self.deleted_archive_dir_count,
            "missingArticleIds": list(self.missing_article_ids),
            "failures": [failure.__dict__ for failure in self.failures],
        }


class ArchiveDeleteService:
    """删除数据档案记录及其本地归档目录。

    SQLiteStore 只负责数据库表变更，ArchiveStorageInfoResolver 只负责目录定位；
    本服务负责把“先删本地归档，再删索引记录”的业务流程串起来。
    """

    def __init__(self, store: SQLiteStore, storage_root: str | Path) -> None:
        self.store = store
        self.storage_root = Path(storage_root)
        self.archive_resolver = ArchiveStorageInfoResolver(self.storage_root)

    def delete_articles(self, article_ids: Iterable[int]) -> ArchiveDeleteResult:
        safe_ids = _unique_positive_ids(article_ids)
        result = ArchiveDeleteResult()
        if not safe_ids:
            return result

        rows = self.store.get_public_articles_by_ids(safe_ids)
        found_ids = {int(row["id"]) for row in rows}
        result.missing_article_ids = [article_id for article_id in safe_ids if article_id not in found_ids]
        cleanup_dirs: set[Path] = set()

        for row in rows:
            archive_info = self.archive_resolver.resolve_for_row(row)
            for archive_dir in archive_info.archive_dirs:
                cleanup_dirs.add(archive_dir.parent)
                if self._delete_archive_dir(archive_dir, result):
                    result.deleted_archive_dir_count += 1

        for directory in sorted(cleanup_dirs, key=lambda item: len(item.parts), reverse=True):
            self._delete_empty_dir(directory, result)

        result.deleted_article_count += self.store.delete_public_articles_by_ids([int(row["id"]) for row in rows])
        return result

    def delete_account(self, account_id: int) -> ArchiveDeleteResult:
        result = ArchiveDeleteResult()
        safe_account_id = int(account_id)
        article_ids = self.store.list_public_article_ids_by_account(safe_account_id)
        result.merge(self.delete_articles(article_ids))
        result.deleted_account_count += self.store.delete_public_account(safe_account_id)
        return result

    def delete_all(self) -> ArchiveDeleteResult:
        result = ArchiveDeleteResult()
        account_ids = [int(row["id"]) for row in self.store.list_public_accounts()]
        for account_id in account_ids:
            result.merge(self.delete_account(account_id))
        return result

    def _delete_archive_dir(self, archive_dir: Path, result: ArchiveDeleteResult) -> bool:
        try:
            resolved_storage_root = self.storage_root.resolve()
            resolved_archive_dir = archive_dir.resolve()
            # 删除操作必须限制在归档根目录内，避免异常数据导致误删项目外文件。
            if resolved_archive_dir == resolved_storage_root or not resolved_archive_dir.is_relative_to(resolved_storage_root):
                result.failures.append(ArchiveDeleteFailure(path=str(archive_dir), error="archive dir is outside storage root"))
                return False
            if not archive_dir.exists():
                return False
            shutil.rmtree(archive_dir)
            return True
        except OSError as exc:
            result.failures.append(ArchiveDeleteFailure(path=str(archive_dir), error=str(exc)))
            return False

    def _delete_empty_dir(self, directory: Path, result: ArchiveDeleteResult) -> None:
        try:
            resolved_storage_root = self.storage_root.resolve()
            resolved_directory = directory.resolve()
            if resolved_directory == resolved_storage_root or not resolved_directory.is_relative_to(resolved_storage_root):
                return
            if directory.exists() and directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
        except OSError as exc:
            result.failures.append(ArchiveDeleteFailure(path=str(directory), error=str(exc)))


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


__all__ = [
    "ArchiveDeleteFailure",
    "ArchiveDeleteResult",
    "ArchiveDeleteService",
]
