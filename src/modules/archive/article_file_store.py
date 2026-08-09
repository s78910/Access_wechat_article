from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal


ReplacementState = Literal["active", "committed", "rolled_back"]


@dataclass(slots=True)
class FileReplacement:
    """一次资源替换的补偿句柄，由业务事务决定提交或回滚。"""

    target_root: Path
    backup_root: Path
    resource_paths: tuple[Path, ...]
    target_created: bool
    _state: ReplacementState = field(default="active", init=False)

    def commit(self) -> None:
        if self._state == "committed":
            return
        if self._state == "rolled_back":
            raise RuntimeError("资源替换已经回滚，不能再提交")
        _remove_exact_resource(self.backup_root)
        self._state = "committed"

    def rollback(self) -> None:
        if self._state == "rolled_back":
            return
        if self._state == "committed":
            raise RuntimeError("资源替换已经提交，不能再回滚")

        for relative_path in reversed(self.resource_paths):
            target = self.target_root / relative_path
            backup = self.backup_root / relative_path
            _remove_exact_resource(target)
            if backup.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(backup, target)

        _remove_exact_resource(self.backup_root)
        if self.target_created:
            _remove_empty_tree(self.target_root)
        self._state = "rolled_back"


class ArticleFileStore:
    def replace_resources(
        self,
        *,
        stage_root: str | Path,
        target_root: str | Path,
        backup_root: str | Path,
        resource_paths: Iterable[str | Path],
    ) -> FileReplacement:
        stage = Path(stage_root).resolve()
        target = Path(target_root).resolve()
        backup = Path(backup_root).resolve()
        resources = _normalize_resource_paths(resource_paths)

        if not resources:
            raise ValueError("resource_paths 不能为空")
        if backup.exists():
            raise ValueError("backup_root 必须是本次任务尚未使用的目录")
        if target == backup or target.is_relative_to(backup) or backup.is_relative_to(target):
            raise ValueError("backup_root 不能与 target_root 重叠")
        if target.anchor.casefold() != backup.anchor.casefold():
            raise ValueError("backup_root 和 target_root 必须位于同一文件系统")

        missing = [relative.as_posix() for relative in resources if not (stage / relative).exists()]
        if missing:
            raise FileNotFoundError(f"暂存资源不存在：{', '.join(missing)}")

        for relative in resources:
            staged_resource = (stage / relative).resolve()
            if not staged_resource.is_relative_to(stage):
                raise ValueError(f"暂存资源越界：{relative.as_posix()}")

        target_created = not target.exists()
        target.mkdir(parents=True, exist_ok=True)
        backup.mkdir(parents=True, exist_ok=False)
        processed: list[Path] = []

        try:
            for relative in resources:
                staged_resource = stage / relative
                target_resource = target / relative
                backup_resource = backup / relative
                # 在任何移动前登记，确保中途异常也能恢复本资源的旧版本。
                processed.append(relative)
                target_resource.parent.mkdir(parents=True, exist_ok=True)
                if target_resource.exists():
                    backup_resource.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(target_resource, backup_resource)
                os.replace(staged_resource, target_resource)
        except Exception:
            replacement = FileReplacement(
                target_root=target,
                backup_root=backup,
                resource_paths=tuple(processed),
                target_created=target_created,
            )
            replacement.rollback()
            raise

        return FileReplacement(
            target_root=target,
            backup_root=backup,
            resource_paths=resources,
            target_created=target_created,
        )


def _normalize_resource_paths(resource_paths: Iterable[str | Path]) -> tuple[Path, ...]:
    normalized: list[Path] = []
    seen: set[str] = set()
    for value in resource_paths:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or path == Path("."):
            raise ValueError(f"资源路径必须是安全相对路径：{value}")
        key = path.as_posix().casefold()
        if key in seen:
            raise ValueError(f"资源路径重复：{value}")
        seen.add(key)
        normalized.append(path)
    return tuple(normalized)


def _remove_exact_resource(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def _remove_empty_tree(root: Path) -> None:
    if not root.is_dir():
        return
    directories = sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for directory in directories:
        try:
            directory.rmdir()
        except OSError:
            pass
    try:
        root.rmdir()
    except OSError:
        pass
