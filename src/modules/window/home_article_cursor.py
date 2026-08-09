from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Protocol

from src.domain.models import ArticleTarget
from src.modules.window.article_card_reader import normalize_window_text
from src.modules.window.window_models import WindowInfo


class ArticleReader(Protocol):
    def read(self, home_window: WindowInfo, *, account_name: str = "") -> list[ArticleTarget]: ...


class HomeScroller(Protocol):
    def scroll(
        self,
        home_window: WindowInfo,
        *,
        visible_targets: list[ArticleTarget],
        direction: str,
        wheel_steps: int | None = None,
    ) -> bool: ...


class TargetRefreshError(RuntimeError):
    """点击前无法在当前主页快照中唯一确认目标。"""


@dataclass(frozen=True, slots=True)
class _ReaderViewport:
    targets: tuple[ArticleTarget, ...]
    visible_signature: tuple[str, ...]
    loading: bool


class HomeArticleCursor:
    """缓存当前屏文章；按成功篇数校准，滚动后立即生成新快照。"""

    def __init__(
        self,
        *,
        reader: ArticleReader,
        account_name: str = "",
        scroller: HomeScroller | None = None,
        max_scroll_attempts: int = 5,
        scroll_wait_seconds: float = 0.5,
        scroll_probe_interval_seconds: float = 0.1,
        scroll_probe_max_interval_seconds: float = 0.4,
        scroll_settle_timeout_seconds: float = 1.2,
        lazy_load_timeout_seconds: float = 3.0,
        unchanged_before_bounce_seconds: float = 0.6,
        snapshot_max_age_seconds: float = 20.0,
        bounce_enabled: bool = True,
        bounce_attempts: int = 2,
        bounce_up_steps: int = 2,
        bounce_down_steps: int = 6,
        bounce_pause_seconds: float = 0.2,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._reader = reader
        self._account_name = account_name
        self._scroller = scroller
        self._max_scroll_attempts = max(0, int(max_scroll_attempts))
        self._scroll_wait_seconds = max(0.0, float(scroll_wait_seconds))
        self._scroll_probe_interval_seconds = max(
            0.01,
            float(scroll_probe_interval_seconds),
        )
        self._scroll_probe_max_interval_seconds = max(
            self._scroll_probe_interval_seconds,
            float(scroll_probe_max_interval_seconds),
        )
        self._scroll_settle_timeout_seconds = max(
            0.0,
            float(scroll_settle_timeout_seconds),
        )
        self._lazy_load_timeout_seconds = max(
            self._scroll_settle_timeout_seconds,
            float(lazy_load_timeout_seconds),
        )
        self._unchanged_before_bounce_seconds = max(
            0.0,
            float(unchanged_before_bounce_seconds),
        )
        self._snapshot_max_age_seconds = max(0.1, float(snapshot_max_age_seconds))
        self._bounce_enabled = bool(bounce_enabled)
        self._bounce_attempts = max(0, int(bounce_attempts))
        self._bounce_up_steps = max(1, int(bounce_up_steps))
        self._bounce_down_steps = max(1, int(bounce_down_steps))
        self._bounce_pause_seconds = max(0.0, float(bounce_pause_seconds))
        self._sleep = sleep
        self._monotonic = monotonic

        self._processed_fingerprints: set[str] = set()
        self._visible_snapshot: list[ArticleTarget] = []
        self._snapshot_loaded = False
        self._snapshot_created_at = 0.0
        self._snapshot_home_key: tuple[int, tuple[int, int, int, int]] | None = None
        self._visible_signature: tuple[str, ...] = ()
        self._viewport_loading = False

        self._scan_count = 0
        self._scan_duration_seconds = 0.0
        self._cache_candidate_count = 0
        self._scroll_down_count = 0
        self._scroll_up_count = 0
        self._bounce_count = 0
        self._scroll_probe_count = 0
        self._loading_wait_count = 0
        self._interference_view_count = 0
        self._scroll_wait_duration_seconds = 0.0

    @property
    def diagnostics(self) -> dict[str, int | float]:
        return {
            "scan_count": self._scan_count,
            "scan_duration_seconds": round(self._scan_duration_seconds, 3),
            "cache_candidate_count": self._cache_candidate_count,
            "scroll_down_count": self._scroll_down_count,
            "scroll_up_count": self._scroll_up_count,
            "bounce_count": self._bounce_count,
            "scroll_probe_count": self._scroll_probe_count,
            "loading_wait_count": self._loading_wait_count,
            "interference_view_count": self._interference_view_count,
            "scroll_wait_duration_seconds": round(
                self._scroll_wait_duration_seconds,
                3,
            ),
        }

    @property
    def visible_snapshot(self) -> list[ArticleTarget]:
        return list(self._visible_snapshot)

    def refresh_visible(self, home_window: WindowInfo) -> list[ArticleTarget]:
        return list(self._refresh_snapshot(home_window))

    def invalidate_snapshot(self) -> None:
        self._snapshot_loaded = False
        self._visible_snapshot = []
        self._snapshot_home_key = None
        self._visible_signature = ()
        self._viewport_loading = False

    def next_candidate(self, home_window: WindowInfo) -> ArticleTarget | None:
        if self._snapshot_needs_refresh(home_window):
            self._refresh_snapshot(home_window)
        candidate = self._first_unprocessed(self._visible_snapshot)
        if candidate is not None:
            self._cache_candidate_count += 1
            return candidate
        if self._scroller is None:
            return None
        return self._scroll_until_candidate(home_window)

    def mark_processed(self, target: ArticleTarget) -> None:
        if target.fingerprint in self._processed_fingerprints:
            return
        self._processed_fingerprints.add(target.fingerprint)

    def refresh_target(
        self,
        home_window: WindowInfo,
        target: ArticleTarget,
    ) -> ArticleTarget:
        resolved = self._resolve_target(self._visible_snapshot, target)
        if resolved is not None and self._snapshot_matches_home(home_window):
            return resolved

        current = self._refresh_snapshot(home_window)
        resolved = self._resolve_target(current, target)
        if resolved is not None:
            return resolved
        raise TargetRefreshError(f"点击前目标已不在当前可见区域：{target.title}")

    def _snapshot_needs_refresh(self, home_window: WindowInfo) -> bool:
        if not self._snapshot_loaded or not self._snapshot_matches_home(home_window):
            return True
        return self._monotonic() - self._snapshot_created_at >= self._snapshot_max_age_seconds

    def _snapshot_matches_home(self, home_window: WindowInfo) -> bool:
        return self._snapshot_home_key == (home_window.handle, home_window.rect)

    def _refresh_snapshot(self, home_window: WindowInfo) -> list[ArticleTarget]:
        started_at = self._monotonic()
        observation = self._read_viewport(home_window)
        visible = list(observation.targets)
        self._scan_duration_seconds += max(0.0, self._monotonic() - started_at)
        self._scan_count += 1
        self._visible_snapshot = visible
        self._snapshot_loaded = True
        self._snapshot_created_at = self._monotonic()
        self._snapshot_home_key = (home_window.handle, home_window.rect)
        self._visible_signature = observation.visible_signature
        self._viewport_loading = observation.loading
        return visible

    def _read_viewport(self, home_window: WindowInfo) -> _ReaderViewport:
        read_viewport = getattr(self._reader, "read_viewport", None)
        if callable(read_viewport):
            value = read_viewport(home_window, account_name=self._account_name)
            targets = tuple(getattr(value, "targets", ()) or ())
            raw_signature = tuple(getattr(value, "visible_signature", ()) or ())
            signature = tuple(
                normalized
                for item in raw_signature
                if (normalized := normalize_window_text(str(item)))
            )
            if not signature:
                signature = self._content_signature(list(targets))
            return _ReaderViewport(
                targets=targets,
                visible_signature=signature,
                loading=bool(getattr(value, "loading", False)),
            )

        targets = tuple(
            self._reader.read(home_window, account_name=self._account_name)
        )
        return _ReaderViewport(
            targets=targets,
            visible_signature=self._content_signature(list(targets)),
            loading=False,
        )

    def _scroll_until_candidate(self, home_window: WindowInfo) -> ArticleTarget | None:
        before_content = self._content_signature(self._visible_snapshot)
        before_viewport = self._viewport_signature(self._visible_snapshot)
        before_visible = self._visible_signature
        bounce_used = 0

        for _attempt in range(self._max_scroll_attempts):
            if not self._send_scroll(home_window, direction="down", wheel_steps=None):
                return None
            self._scroll_down_count += 1
            status, candidate = self._wait_for_scroll_result(
                home_window,
                before_content=before_content,
                before_viewport=before_viewport,
                before_visible=before_visible,
            )
            if candidate is not None:
                return candidate

            after_content = self._content_signature(self._visible_snapshot)
            after_viewport = self._viewport_signature(self._visible_snapshot)
            after_visible = self._visible_signature
            if (
                status == "unchanged"
                and self._bounce_enabled
                and bounce_used < self._bounce_attempts
            ):
                bounce_used += 1
                candidate = self._bounce_for_lazy_load(home_window)
                if candidate is not None:
                    return candidate
                after_content = self._content_signature(self._visible_snapshot)
                after_viewport = self._viewport_signature(self._visible_snapshot)
                after_visible = self._visible_signature

            before_content = after_content
            before_viewport = after_viewport
            before_visible = after_visible
        return None

    def _wait_for_scroll_result(
        self,
        home_window: WindowInfo,
        *,
        before_content: tuple[str, ...],
        before_viewport: tuple[tuple[str, int, int], ...],
        before_visible: tuple[str, ...],
    ) -> tuple[str, ArticleTarget | None]:
        self._wait(self._scroll_wait_seconds)
        started_at = self._monotonic()
        interval = self._scroll_probe_interval_seconds

        while True:
            visible = self._refresh_snapshot(home_window)
            self._scroll_probe_count += 1
            candidate = self._first_unprocessed(visible)
            if candidate is not None:
                self._cache_candidate_count += 1
                return "candidate", candidate

            after_content = self._content_signature(visible)
            after_viewport = self._viewport_signature(visible)
            changed = (
                after_content != before_content
                or after_viewport != before_viewport
                or self._visible_signature != before_visible
            )
            elapsed = max(0.0, self._monotonic() - started_at)

            if self._viewport_loading:
                self._loading_wait_count += 1
                if elapsed >= self._lazy_load_timeout_seconds:
                    return "unchanged", None
                remaining = self._lazy_load_timeout_seconds - elapsed
                self._wait(min(interval, remaining))
                interval = min(
                    self._scroll_probe_max_interval_seconds,
                    interval * 1.5,
                )
                continue

            if changed:
                if not visible:
                    self._interference_view_count += 1
                return "changed", None

            unchanged_limit = min(
                self._scroll_settle_timeout_seconds,
                self._unchanged_before_bounce_seconds,
            )
            if elapsed >= unchanged_limit:
                return "unchanged", None
            remaining = unchanged_limit - elapsed
            self._wait(min(interval, remaining))
            interval = min(
                self._scroll_probe_max_interval_seconds,
                interval * 1.5,
            )

    def _bounce_for_lazy_load(self, home_window: WindowInfo) -> ArticleTarget | None:
        if not self._send_scroll(
            home_window,
            direction="up",
            wheel_steps=self._bounce_up_steps,
        ):
            return None
        self._scroll_up_count += 1
        self._wait(self._bounce_pause_seconds)

        if not self._send_scroll(
            home_window,
            direction="down",
            wheel_steps=self._bounce_down_steps,
        ):
            return None
        self._scroll_down_count += 1
        self._bounce_count += 1
        _status, candidate = self._wait_for_scroll_result(
            home_window,
            before_content=self._content_signature(self._visible_snapshot),
            before_viewport=self._viewport_signature(self._visible_snapshot),
            before_visible=self._visible_signature,
        )
        return candidate

    def _send_scroll(
        self,
        home_window: WindowInfo,
        *,
        direction: str,
        wheel_steps: int | None,
    ) -> bool:
        if self._scroller is None:
            return False
        scroll = getattr(self._scroller, "scroll", None)
        if callable(scroll):
            return bool(
                scroll(
                    home_window,
                    visible_targets=list(self._visible_snapshot),
                    direction=direction,
                    wheel_steps=wheel_steps,
                )
            )
        if direction == "down":
            legacy = getattr(self._scroller, "scroll_down", None)
            if callable(legacy):
                return bool(
                    legacy(
                        home_window,
                        visible_targets=list(self._visible_snapshot),
                    )
                )
        return False

    def _wait(self, seconds: float) -> None:
        if seconds > 0:
            self._sleep(seconds)
            self._scroll_wait_duration_seconds += seconds

    def _first_unprocessed(self, visible: list[ArticleTarget]) -> ArticleTarget | None:
        for target in visible:
            if target.fingerprint not in self._processed_fingerprints:
                return target
        return None

    @staticmethod
    def _resolve_target(
        visible: list[ArticleTarget],
        target: ArticleTarget,
    ) -> ArticleTarget | None:
        fingerprint_matches = [
            item for item in visible if item.fingerprint == target.fingerprint
        ]
        if len(fingerprint_matches) == 1:
            return fingerprint_matches[0]

        normalized_title = normalize_window_text(target.title)
        title_matches = [
            item
            for item in visible
            if normalize_window_text(item.title) == normalized_title
        ]
        if len(title_matches) == 1:
            return title_matches[0]
        if len(title_matches) > 1:
            raise TargetRefreshError(
                f"点击前发现多个同标题候选，无法安全确认：{target.title}"
            )
        return None

    @staticmethod
    def _content_signature(visible: list[ArticleTarget]) -> tuple[str, ...]:
        return tuple(item.fingerprint for item in visible)

    @staticmethod
    def _viewport_signature(
        visible: list[ArticleTarget],
    ) -> tuple[tuple[str, int, int], ...]:
        return tuple(
            (item.fingerprint, item.click_x, item.click_y)
            for item in visible
        )


__all__ = ["HomeArticleCursor", "TargetRefreshError"]
