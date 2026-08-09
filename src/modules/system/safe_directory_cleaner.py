from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class DirectoryCleanResult:
    """目录内容清理结果；计数只包含已经成功删除的项目。"""

    ok: bool = True
    status: str = "cleared"
    removed_file_count: int = 0
    removed_directory_count: int = 0
    freed_bytes: int = 0
    skipped: list[dict[str, str]] = field(default_factory=list)

    @property
    def removed_count(self) -> int:
        return self.removed_file_count + self.removed_directory_count

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)


class SafeDirectoryCleaner:
    """只删除指定目录的内容，保留根目录且不跟随符号链接或目录联接。"""

    def clear_contents(self, directory: str | Path) -> DirectoryCleanResult:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        result = DirectoryCleanResult()

        for child in list(target.iterdir()):
            self._remove_path(child, result)

        if result.skipped:
            result.ok = False
            result.status = "partial"
        return result

    def _remove_path(self, path: Path, result: DirectoryCleanResult) -> None:
        try:
            is_link = path.is_symlink()
            is_junction = _is_junction(path)
            if is_link or is_junction:
                was_directory = path.is_dir()
                freed_bytes = _lstat_size(path)
                if is_junction:
                    path.rmdir()
                else:
                    path.unlink()
                self._record_removed(
                    result,
                    is_directory=was_directory,
                    freed_bytes=freed_bytes,
                )
                return

            if path.is_dir():
                for child in list(path.iterdir()):
                    self._remove_path(child, result)

                # 子项删除失败时保留父目录，避免把同一个占用问题重复计入 skipped。
                if any(path.iterdir()):
                    return
                path.rmdir()
                result.removed_directory_count += 1
                return

            freed_bytes = _lstat_size(path)
            path.unlink()
            self._record_removed(
                result,
                is_directory=False,
                freed_bytes=freed_bytes,
            )
        except Exception as exc:
            result.skipped.append({"path": str(path), "error": str(exc)})

    @staticmethod
    def _record_removed(
        result: DirectoryCleanResult,
        *,
        is_directory: bool,
        freed_bytes: int,
    ) -> None:
        if is_directory:
            result.removed_directory_count += 1
        else:
            result.removed_file_count += 1
        result.freed_bytes += max(0, freed_bytes)


def _is_junction(path: Path) -> bool:
    checker: Any = getattr(path, "is_junction", None)
    return bool(checker()) if callable(checker) else False


def _lstat_size(path: Path) -> int:
    try:
        return int(path.lstat().st_size)
    except OSError:
        return 0


__all__ = ["DirectoryCleanResult", "SafeDirectoryCleaner"]
