from __future__ import annotations

from pathlib import Path
from typing import Literal

from src.core.config import AppRuntimeConfig, LOG_DIR, PROJECT_ROOT
from src.modules.storage.archive_storage_info import default_storage_root_for_db


RuntimePathKey = Literal["projectDir", "outputDir", "storageDir", "logDir"]

RUNTIME_PATH_KEYS: tuple[RuntimePathKey, ...] = ("projectDir", "outputDir", "storageDir", "logDir")


def build_runtime_paths(config: AppRuntimeConfig) -> dict[str, str]:
    """返回系统配置页展示的真实运行目录，避免前端硬编码本机旧路径。"""
    return {
        "projectDir": str(PROJECT_ROOT),
        "outputDir": str(LOG_DIR / "article_capture"),
        "storageDir": str(default_storage_root_for_db(config.storage.db_path)),
        "logDir": str(LOG_DIR),
    }


def resolve_runtime_path(config: AppRuntimeConfig, key: str) -> Path:
    """按前端传入的目录 key 解析实际目录；非法 key 交给调用层返回清晰错误。"""
    paths = build_runtime_paths(config)
    if key not in paths:
        raise KeyError(key)
    return Path(paths[key])
