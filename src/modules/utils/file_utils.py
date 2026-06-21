from __future__ import annotations

import re
from pathlib import Path


def ensure_directory(path: str | Path) -> Path:
    """确保本地目录存在，并返回 Path 对象。"""
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def list_directory(path: str | Path) -> list[dict]:
    """列出目录直属内容，供页面或调试工具展示基础文件信息。"""
    directory = Path(path)
    if not directory.exists():
        return []

    entries = []
    for child in sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        stat = child.stat()
        entries.append(
            {
                "name": child.name,
                "path": str(child),
                "isDir": child.is_dir(),
                "size": stat.st_size,
                "modifiedAt": stat.st_mtime,
            }
        )
    return entries


def clean_path_part(value: str, max_length: int = 120) -> str:
    """清洗 Windows 路径片段，避免公众号名、文章标题生成非法目录名。"""
    text = re.sub(r'[<>:"/\\|?*]+', "_", str(value or "")).strip(" ._")
    text = re.sub(r"\s+", " ", text)
    if not text:
        text = "未命名"
    return text[:max_length].rstrip(" ._") or "未命名"
