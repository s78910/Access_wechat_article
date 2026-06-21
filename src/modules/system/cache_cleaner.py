from __future__ import annotations

import shutil
from pathlib import Path


def clear_directory_contents(directory: str | Path) -> dict:
    """清空指定目录下的文件和子目录，保留目录本身。"""
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)

    removed: list[str] = []
    skipped: list[dict] = []

    for child in target.iterdir():
        try:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
            removed.append(str(child))
        except Exception as exc:
            skipped.append({"path": str(child), "error": str(exc)})

    skipped_count = len(skipped)
    removed_count = len(removed)
    ok = skipped_count == 0

    return {
        "ok": ok,
        "status": "cleared" if ok else "partial",
        "removedCount": removed_count,
        "skippedCount": skipped_count,
        "skipped": skipped,
        "message": (
            f"已清理 {removed_count} 项缓存。"
            if ok
            else f"已清理 {removed_count} 项缓存，{skipped_count} 项被占用或无权限。"
        ),
    }


def clear_directory_contents_except(
    directory: str | Path,
    keep_paths: list[str | Path] | tuple[str | Path, ...] | None = None,
) -> dict:
    """清空目录内容，但保留当前运行日志等指定路径。"""
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    keep_set = {Path(item).resolve() for item in (keep_paths or [])}

    removed: list[str] = []
    skipped: list[dict] = []

    for child in target.iterdir():
        try:
            _remove_path_except(child, keep_set, removed, skipped)
        except Exception as exc:
            skipped.append({"path": str(child), "error": str(exc)})

    kept_count = sum(1 for item in skipped if item.get("error") == "kept-current-session")
    failed_count = len(skipped) - kept_count
    removed_count = len(removed)
    ok = failed_count == 0

    return {
        "ok": ok,
        "status": "cleared" if ok else "partial",
        "removedCount": removed_count,
        "keptCount": kept_count,
        "skippedCount": failed_count,
        "skipped": skipped,
        "message": (
            f"已清理 {removed_count} 项缓存，保留当前运行记录。"
            if ok and kept_count
            else f"已清理 {removed_count} 项缓存。"
            if ok
            else f"已清理 {removed_count} 项缓存，保留当前运行记录，另有 {failed_count} 项被占用或无权限。"
        ),
    }


def _remove_path_except(path: Path, keep_set: set[Path], removed: list[str], skipped: list[dict]) -> None:
    resolved_path = path.resolve()
    if resolved_path in keep_set:
        skipped.append({"path": str(path), "error": "kept-current-session"})
        return

    if path.is_dir() and not path.is_symlink():
        if any(keep_path == resolved_path or resolved_path in keep_path.parents for keep_path in keep_set):
            for child in path.iterdir():
                _remove_path_except(child, keep_set, removed, skipped)
            if not any(path.iterdir()):
                path.rmdir()
                removed.append(str(path))
            return

        shutil.rmtree(path)
        removed.append(str(path))
        return

    path.unlink()
    removed.append(str(path))
