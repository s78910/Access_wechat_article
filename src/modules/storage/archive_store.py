from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def ensure_archive_dir(path: str | Path) -> Path:
    """创建本地归档目录，并返回 Path 对象。"""
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def write_json_file(path: str | Path, data: Any) -> Path:
    """按 UTF-8 写入格式化 JSON 文件，供文章详情、评论详情等复用。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def write_text_file(path: str | Path, content: str) -> Path:
    """写入文本文件，主要用于 HTML、调试文本等归档内容。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(content or ""), encoding="utf-8")
    return target


__all__ = ["ensure_archive_dir", "write_json_file", "write_text_file"]
