from __future__ import annotations

from dataclasses import dataclass

from src.modules.html_archive.models import ArticleHtmlArchiveConfig


@dataclass(frozen=True)
class ScrollSnapshot:
    scroll_top: int
    viewport_height: int
    scroll_height: int
    target_bottom: int
    image_count: int
    pending_lazy_count: int
    resource_count: int
    elapsed_seconds: float
    scroll_count: int


@dataclass(frozen=True)
class ScrollDecision:
    stop: bool
    reason: str
    snapshot: ScrollSnapshot


class AdaptiveScrollController:
    """根据页面高度、懒加载数量和资源变化判断是否继续滚动。"""

    def __init__(self, config: ArticleHtmlArchiveConfig) -> None:
        self.config = config
        self._previous: ScrollSnapshot | None = None
        self._stable_rounds = 0

    def evaluate(self, snapshot: ScrollSnapshot) -> ScrollDecision:
        if snapshot.elapsed_seconds >= self.config.max_scroll_seconds:
            return ScrollDecision(True, "max_scroll_seconds", snapshot)
        if snapshot.scroll_count >= self.config.max_scrolls:
            return ScrollDecision(True, "max_scrolls", snapshot)
        if self._is_short_page(snapshot) and snapshot.pending_lazy_count == 0:
            return ScrollDecision(True, "short_page_loaded", snapshot)

        stable = self._is_stable(snapshot)
        if stable:
            self._stable_rounds += 1
        else:
            self._stable_rounds = 0

        near_bottom = snapshot.scroll_top + snapshot.viewport_height >= snapshot.target_bottom - self._bottom_margin(snapshot)
        if near_bottom and snapshot.pending_lazy_count == 0 and self._stable_rounds == 0:
            # 到达正文底部后，当前快照先作为稳定判断的基准，避免超长文章多等一轮。
            self._stable_rounds = 1
        if near_bottom and snapshot.pending_lazy_count == 0 and self._stable_rounds >= self.config.stable_rounds:
            return ScrollDecision(True, "article_bottom_stable", snapshot)

        return ScrollDecision(False, "continue", snapshot)

    def next_scroll_distance(self, snapshot: ScrollSnapshot) -> int:
        viewport = max(1, int(snapshot.viewport_height or self.config.viewport_height))
        return max(200, int(viewport * self.config.scroll_step_ratio))

    def _is_short_page(self, snapshot: ScrollSnapshot) -> bool:
        viewport = max(1, snapshot.viewport_height)
        target_bottom = snapshot.target_bottom or snapshot.scroll_height
        return target_bottom <= viewport * 1.1 and snapshot.scroll_height <= viewport * 1.2

    def _is_stable(self, snapshot: ScrollSnapshot) -> bool:
        previous = self._previous
        self._previous = snapshot
        if previous is None:
            return False
        return (
            snapshot.scroll_height == previous.scroll_height
            and snapshot.image_count == previous.image_count
            and snapshot.resource_count == previous.resource_count
            and snapshot.pending_lazy_count == previous.pending_lazy_count
        )

    @staticmethod
    def _bottom_margin(snapshot: ScrollSnapshot) -> int:
        return max(200, int(snapshot.viewport_height * 0.35))


__all__ = ["AdaptiveScrollController", "ScrollDecision", "ScrollSnapshot"]
