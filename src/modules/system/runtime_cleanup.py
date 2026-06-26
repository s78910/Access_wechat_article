from __future__ import annotations

from pathlib import Path
from typing import Any

from src.core.config import AppRuntimeConfig, TMP_DIR
from src.modules.system.cache_cleaner import clear_directory_contents_except


def run_startup_temp_cleanup(
    config: AppRuntimeConfig,
    *,
    temp_dir: str | Path = TMP_DIR,
    keep_paths: list[str | Path] | tuple[str | Path, ...] | None = None,
) -> dict[str, Any]:
    """按启动配置清理上次遗留的临时目录；关闭开关时只返回跳过结果。"""
    if not bool(config.app.auto_clean_temp_files):
        return {
            "ok": True,
            "status": "disabled",
            "removedCount": 0,
            "keptCount": 0,
            "skippedCount": 0,
            "skipped": [],
            "message": "自动清理临时文件已关闭。",
        }

    return clear_directory_contents_except(temp_dir, keep_paths)


__all__ = ["run_startup_temp_cleanup"]
