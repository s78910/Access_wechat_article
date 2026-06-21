from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from src.modules.detail.comment_detail import fetch_comments_to_archive

CommentFetcher = Callable[..., dict[str, Any]]


class CommentService:
    """评论信息业务入口。

    目前只负责调用评论请求模块。后续需要分页策略、图片下载策略或失败重试时，
    都可以先集中到这里处理。
    """

    def __init__(self, *, fetch_comments: CommentFetcher = fetch_comments_to_archive) -> None:
        self._fetch_comments = fetch_comments

    def fetch_comments_to_archive(
        self,
        keyed_url: str,
        source_html: str,
        archive_dir: str | Path,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self._fetch_comments(keyed_url, source_html, Path(archive_dir), **kwargs)
