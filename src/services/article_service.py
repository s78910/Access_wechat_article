from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from src.modules.detail.article_detail import (
    fetch_article_detail_from_keyed_url,
    write_article_detail_json,
)

ArticleDetailFetcher = Callable[..., dict[str, Any]]


class ArticleService:
    """文章详情业务入口。

    当前先封装“用带 key 的 URL 获取文章详情并写入 article_detail.json”这一件事。
    后续如果文章保存规则变化，只优先改这里，不要让调用方到处拼流程。
    """

    def __init__(
        self,
        *,
        fetch_detail: ArticleDetailFetcher = fetch_article_detail_from_keyed_url,
        write_detail=write_article_detail_json,
    ) -> None:
        self._fetch_detail = fetch_detail
        self._write_detail = write_detail

    def fetch_detail_to_archive(
        self,
        keyed_url: str,
        article_dir: str | Path,
        *,
        request_headers: dict[str, Any] | None = None,
        timeout_seconds: float = 10.0,
        collect_time: str | None = None,
    ) -> dict[str, Any]:
        detail = self._fetch_detail(
            keyed_url,
            request_headers=request_headers,
            timeout_seconds=timeout_seconds,
            collect_time=collect_time,
        )
        detail_path = self._write_detail(detail, article_dir)
        return {
            "article_detail_path": str(detail_path),
            "detail": detail,
        }
