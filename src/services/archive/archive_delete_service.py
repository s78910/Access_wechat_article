from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.storage.sqlite.connection import sqlite_connection


@dataclass(frozen=True, slots=True)
class ArchiveDeleteArticle:
    id: int
    account_id: int
    archive_dir: str


@dataclass(frozen=True, slots=True)
class StagedArchivePath:
    original: Path
    staged: Path


class ArchiveDeleteService:
    """删除数据档案数据库记录，并清理对应本地归档目录。"""

    def delete_articles(
        self,
        *,
        database_path: str | Path,
        storage_root: str | Path,
        article_ids: list[int],
    ) -> dict[str, Any]:
        selected_ids = self._normalize_ids(article_ids)
        if not selected_ids:
            return self._result(
                ok=False,
                status="failed",
                message="请先选择需要删除的文章记录。",
            )

        storage_root_path = Path(storage_root).resolve()
        articles = self._load_articles(database_path, selected_ids)
        found_ids = {article.id for article in articles}
        missing_article_ids = [article_id for article_id in selected_ids if article_id not in found_ids]

        staged_paths, staging_dir, stage_failures = self._stage_archive_dirs(
            storage_root_path,
            articles,
        )
        if stage_failures:
            return self._result(
                ok=False,
                status="failed",
                missing_article_ids=missing_article_ids,
                failures=stage_failures,
                message=self._message(
                    deleted_article_count=0,
                    deleted_account_count=0,
                    deleted_archive_dir_count=0,
                    failures=stage_failures,
                    missing_article_ids=missing_article_ids,
                ),
            )

        try:
            with sqlite_connection(database_path, write=True) as connection:
                if found_ids:
                    placeholders = ",".join("?" for _ in found_ids)
                    connection.execute(
                        f"DELETE FROM awa_public_articles WHERE id IN ({placeholders})",
                        tuple(found_ids),
                    )
        except Exception as exc:
            restore_failures = self._restore_staged_paths(staged_paths, staging_dir)
            failures = [
                {"path": str(Path(database_path).resolve()), "error": f"数据库删除失败：{exc}"},
                *restore_failures,
            ]
            return self._result(
                ok=False,
                status="failed",
                missing_article_ids=missing_article_ids,
                failures=failures,
                message=self._message(
                    deleted_article_count=0,
                    deleted_account_count=0,
                    deleted_archive_dir_count=0,
                    failures=failures,
                    missing_article_ids=missing_article_ids,
                )
            )

        deleted_dirs, failures = self._purge_staged_paths(staged_paths, staging_dir)
        status = "deleted" if not failures and not missing_article_ids else "partial-failed"
        return self._result(
            ok=not failures,
            status=status,
            deleted_article_count=len(found_ids),
            deleted_archive_dir_count=deleted_dirs,
            missing_article_ids=missing_article_ids,
            failures=failures,
            message=self._message(
                deleted_article_count=len(found_ids),
                deleted_account_count=0,
                deleted_archive_dir_count=deleted_dirs,
                failures=failures,
                missing_article_ids=missing_article_ids,
            ),
        )

    def delete_account(
        self,
        *,
        database_path: str | Path,
        storage_root: str | Path,
        account_id: int,
    ) -> dict[str, Any]:
        selected_account_id = int(account_id)
        with sqlite_connection(database_path, write=False) as connection:
            account = connection.execute(
                "SELECT id FROM awa_public_accounts WHERE id = ?",
                (selected_account_id,),
            ).fetchone()
        if account is None:
            return self._result(
                ok=False,
                status="missing",
                message="未找到需要删除的公众号记录。",
            )

        articles = self._load_account_articles(database_path, selected_account_id)
        storage_root_path = Path(storage_root).resolve()
        staged_paths, staging_dir, stage_failures = self._stage_archive_dirs(
            storage_root_path,
            articles,
        )
        if stage_failures:
            return self._result(
                ok=False,
                status="failed",
                failures=stage_failures,
                message=self._message(
                    deleted_article_count=0,
                    deleted_account_count=0,
                    deleted_archive_dir_count=0,
                    failures=stage_failures,
                    missing_article_ids=[],
                ),
            )

        try:
            with sqlite_connection(database_path, write=True) as connection:
                connection.execute(
                    "DELETE FROM awa_public_articles WHERE account_id = ?",
                    (selected_account_id,),
                )
                connection.execute(
                    "DELETE FROM awa_public_accounts WHERE id = ?",
                    (selected_account_id,),
                )
        except Exception as exc:
            restore_failures = self._restore_staged_paths(staged_paths, staging_dir)
            failures = [
                {"path": str(Path(database_path).resolve()), "error": f"数据库删除失败：{exc}"},
                *restore_failures,
            ]
            return self._result(
                ok=False,
                status="failed",
                failures=failures,
                message=self._message(
                    deleted_article_count=0,
                    deleted_account_count=0,
                    deleted_archive_dir_count=0,
                    failures=failures,
                    missing_article_ids=[],
                ),
            )

        deleted_dirs, failures = self._purge_staged_paths(staged_paths, staging_dir)
        return self._result(
            ok=not failures,
            status="deleted" if not failures else "partial-failed",
            deleted_article_count=len(articles),
            deleted_account_count=1,
            deleted_archive_dir_count=deleted_dirs,
            failures=failures,
            message=self._message(
                deleted_article_count=len(articles),
                deleted_account_count=1,
                deleted_archive_dir_count=deleted_dirs,
                failures=failures,
                missing_article_ids=[],
            ),
        )

    def delete_all(
        self,
        *,
        database_path: str | Path,
        storage_root: str | Path,
    ) -> dict[str, Any]:
        with sqlite_connection(database_path, write=False) as connection:
            account_count = int(connection.execute("SELECT COUNT(*) FROM awa_public_accounts").fetchone()[0])
        articles = self._load_all_articles(database_path)
        storage_root_path = Path(storage_root).resolve()
        staged_paths, staging_dir, stage_failures = self._stage_archive_dirs(
            storage_root_path,
            articles,
        )
        if stage_failures:
            return self._result(
                ok=False,
                status="failed",
                failures=stage_failures,
                message=self._message(
                    deleted_article_count=0,
                    deleted_account_count=0,
                    deleted_archive_dir_count=0,
                    failures=stage_failures,
                    missing_article_ids=[],
                ),
            )

        try:
            with sqlite_connection(database_path, write=True) as connection:
                connection.execute("DELETE FROM awa_public_articles")
                connection.execute("DELETE FROM awa_public_accounts")
        except Exception as exc:
            restore_failures = self._restore_staged_paths(staged_paths, staging_dir)
            failures = [
                {"path": str(Path(database_path).resolve()), "error": f"数据库删除失败：{exc}"},
                *restore_failures,
            ]
            return self._result(
                ok=False,
                status="failed",
                failures=failures,
                message=self._message(
                    deleted_article_count=0,
                    deleted_account_count=0,
                    deleted_archive_dir_count=0,
                    failures=failures,
                    missing_article_ids=[],
                ),
            )

        deleted_dirs, failures = self._purge_staged_paths(staged_paths, staging_dir)
        return self._result(
            ok=not failures,
            status="deleted" if not failures else "partial-failed",
            deleted_article_count=len(articles),
            deleted_account_count=account_count,
            deleted_archive_dir_count=deleted_dirs,
            failures=failures,
            message=self._message(
                deleted_article_count=len(articles),
                deleted_account_count=account_count,
                deleted_archive_dir_count=deleted_dirs,
                failures=failures,
                missing_article_ids=[],
            ),
        )

    def _load_articles(self, database_path: str | Path, article_ids: list[int]) -> list[ArchiveDeleteArticle]:
        placeholders = ",".join("?" for _ in article_ids)
        with sqlite_connection(database_path, write=False) as connection:
            rows = connection.execute(
                f"""
                SELECT id, account_id, archive_dir
                FROM awa_public_articles
                WHERE id IN ({placeholders})
                """,
                tuple(article_ids),
            ).fetchall()
        return [self._article_from_row(row) for row in rows]

    def _load_account_articles(self, database_path: str | Path, account_id: int) -> list[ArchiveDeleteArticle]:
        with sqlite_connection(database_path, write=False) as connection:
            rows = connection.execute(
                """
                SELECT id, account_id, archive_dir
                FROM awa_public_articles
                WHERE account_id = ?
                """,
                (account_id,),
            ).fetchall()
        return [self._article_from_row(row) for row in rows]

    def _load_all_articles(self, database_path: str | Path) -> list[ArchiveDeleteArticle]:
        with sqlite_connection(database_path, write=False) as connection:
            rows = connection.execute(
                """
                SELECT id, account_id, archive_dir
                FROM awa_public_articles
                """
            ).fetchall()
        return [self._article_from_row(row) for row in rows]

    def _article_from_row(self, row: Any) -> ArchiveDeleteArticle:
        return ArchiveDeleteArticle(
            id=int(row["id"]),
            account_id=int(row["account_id"]),
            archive_dir=str(row["archive_dir"] or ""),
        )

    def _stage_archive_dirs(
        self,
        storage_root: Path,
        articles: list[ArchiveDeleteArticle],
    ) -> tuple[list[StagedArchivePath], Path | None, list[dict[str, str]]]:
        targets = self._collect_archive_targets(storage_root, articles)
        existing_targets = [target for target in targets if target.exists()]
        if not existing_targets:
            return [], None, []

        staging_dir = storage_root / ".awa-delete-staging" / uuid4().hex
        staging_dir.mkdir(parents=True, exist_ok=False)
        staged_paths: list[StagedArchivePath] = []
        for index, target in enumerate(existing_targets, start=1):
            staged_path = staging_dir / f"{index:04d}-{target.name}"
            try:
                target.replace(staged_path)
                staged_paths.append(StagedArchivePath(original=target, staged=staged_path))
            except OSError as exc:
                failures = [{"path": str(target), "error": str(exc)}]
                failures.extend(self._restore_staged_paths(staged_paths, staging_dir))
                return [], None, failures
        return staged_paths, staging_dir, []

    def _collect_archive_targets(
        self,
        storage_root: Path,
        articles: list[ArchiveDeleteArticle],
    ) -> list[Path]:
        targets: list[Path] = []
        seen: set[Path] = set()
        for article in articles:
            for target in self._archive_dir_targets(storage_root, article.archive_dir):
                if target in seen:
                    continue
                seen.add(target)
                targets.append(target)
        targets.sort(key=lambda path: len(path.parts), reverse=True)
        return targets

    def _restore_staged_paths(
        self,
        staged_paths: list[StagedArchivePath],
        staging_dir: Path | None,
    ) -> list[dict[str, str]]:
        failures: list[dict[str, str]] = []
        for item in reversed(staged_paths):
            try:
                item.original.parent.mkdir(parents=True, exist_ok=True)
                item.staged.replace(item.original)
            except OSError as exc:
                failures.append({"path": str(item.staged), "error": f"恢复归档目录失败：{exc}"})
        self._remove_empty_staging_dir(staging_dir)
        return failures

    def _purge_staged_paths(
        self,
        staged_paths: list[StagedArchivePath],
        staging_dir: Path | None,
    ) -> tuple[int, list[dict[str, str]]]:
        deleted_count = 0
        failures: list[dict[str, str]] = []
        for item in staged_paths:
            try:
                if item.staged.is_dir():
                    shutil.rmtree(item.staged)
                else:
                    item.staged.unlink()
                deleted_count += 1
            except OSError as exc:
                failures.append({"path": str(item.staged), "error": str(exc)})
        self._remove_empty_staging_dir(staging_dir)
        return deleted_count, failures

    def _remove_empty_staging_dir(self, staging_dir: Path | None) -> None:
        if staging_dir is None:
            return
        try:
            staging_dir.rmdir()
            staging_dir.parent.rmdir()
        except OSError:
            return

    def _archive_dir_targets(self, storage_root: Path, archive_dir: str) -> list[Path]:
        resolved = self._resolve_archive_dir(storage_root, archive_dir)
        if resolved is None:
            return []

        parent = resolved.parent
        targets = [resolved]
        if parent.is_dir():
            duplicate_pattern = re.compile(rf"^{re.escape(resolved.name)}_\d+$")
            for sibling in parent.iterdir():
                if not duplicate_pattern.fullmatch(sibling.name):
                    continue
                if self._is_reparse_point(sibling):
                    continue
                candidate = sibling.resolve()
                if self._is_safe_archive_path(storage_root, candidate):
                    targets.append(candidate)
        return targets

    def _resolve_archive_dir(self, storage_root: Path, archive_dir: str) -> Path | None:
        if not archive_dir.strip():
            return None
        raw_path = Path(archive_dir)
        candidate = raw_path if raw_path.is_absolute() else storage_root / raw_path
        if self._is_reparse_point(candidate):
            return None
        resolved = candidate.resolve()
        if not self._is_safe_archive_path(storage_root, resolved):
            return None
        return resolved

    def _is_safe_archive_path(self, storage_root: Path, candidate: Path) -> bool:
        resolved_root = storage_root.resolve()
        try:
            relative = candidate.resolve().relative_to(resolved_root)
        except ValueError:
            return False
        return bool(relative.parts) and relative.parts[0] != ".awa-delete-staging"

    def _is_reparse_point(self, path: Path) -> bool:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction and is_junction())

    def _normalize_ids(self, values: list[int]) -> list[int]:
        normalized: list[int] = []
        seen: set[int] = set()
        for value in values:
            try:
                item_id = int(value)
            except (TypeError, ValueError):
                continue
            if item_id <= 0 or item_id in seen:
                continue
            normalized.append(item_id)
            seen.add(item_id)
        return normalized

    def _result(
        self,
        *,
        ok: bool,
        status: str,
        deleted_article_count: int = 0,
        deleted_account_count: int = 0,
        deleted_archive_dir_count: int = 0,
        missing_article_ids: list[int] | None = None,
        failures: list[dict[str, str]] | None = None,
        message: str = "",
    ) -> dict[str, Any]:
        return {
            "ok": ok,
            "status": status,
            "deletedArticleCount": deleted_article_count,
            "deletedAccountCount": deleted_account_count,
            "deletedArchiveDirCount": deleted_archive_dir_count,
            "missingArticleIds": missing_article_ids or [],
            "failures": failures or [],
            "message": message,
        }

    def _message(
        self,
        *,
        deleted_article_count: int,
        deleted_account_count: int,
        deleted_archive_dir_count: int,
        failures: list[dict[str, str]],
        missing_article_ids: list[int],
    ) -> str:
        base = (
            f"已删除 {deleted_article_count} 条文章记录、"
            f"{deleted_account_count} 个公众号、"
            f"{deleted_archive_dir_count} 个本地归档目录。"
        )
        if failures:
            return f"{base} 另有 {len(failures)} 个本地目录删除失败。"
        if missing_article_ids:
            return f"{base} 其中 {len(missing_article_ids)} 条文章记录未找到。"
        return base
