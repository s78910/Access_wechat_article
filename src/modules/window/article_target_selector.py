from __future__ import annotations

from collections.abc import Sequence

from src.domain.models import ArticleTarget
from src.modules.window.article_card_reader import normalize_window_text


class ArticleTargetSelectionError(ValueError):
    """当前可见文章无法唯一、安全地对应到用户指定目标。"""


def select_visible_article_target(
    candidates: Sequence[ArticleTarget],
    *,
    article_index: int = 1,
    article_title: str = "",
) -> ArticleTarget:
    """按完整标题或 1-based 序号选择目标；填写标题时标题优先。"""
    expected_title = normalize_window_text(article_title)
    if expected_title:
        matches = [
            candidate
            for candidate in candidates
            if normalize_window_text(candidate.title) == expected_title
        ]
        if not matches:
            raise ArticleTargetSelectionError(
                f"未找到当前可见文章：{expected_title}"
            )
        if len(matches) > 1:
            raise ArticleTargetSelectionError(
                f"当前可见区域存在 {len(matches)} 个同名候选，拒绝点击：{expected_title}"
            )
        return matches[0]

    index = int(article_index)
    if index < 1 or index > len(candidates):
        raise ArticleTargetSelectionError(
            f"文章序号 {index} 超出当前可见范围 1-{len(candidates)}"
        )
    return candidates[index - 1]


__all__ = ["ArticleTargetSelectionError", "select_visible_article_target"]
