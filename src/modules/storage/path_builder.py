from __future__ import annotations

from pathlib import Path

from src.modules.utils.file_utils import clean_path_part
from src.modules.utils.time_utils import format_datetime_for_dir


def build_article_archive_dir(
    *,
    storage_root: str | Path,
    account_name: str,
    published_time: str,
    article_title: str,
) -> Path:
    """生成单篇文章归档目录；如目录已存在，自动追加 _1、_2 这类后缀。"""
    account_dir_name = clean_path_part(account_name)
    time_part = format_datetime_for_dir(published_time)
    title_part = clean_path_part(article_title)
    base_name = f"{time_part} {title_part}".strip()

    account_dir = Path(storage_root) / account_dir_name
    candidate = account_dir / base_name
    if not candidate.exists():
        return candidate

    index = 1
    while True:
        next_candidate = account_dir / f"{base_name}_{index}"
        if not next_candidate.exists():
            return next_candidate
        index += 1


__all__ = ["build_article_archive_dir"]
