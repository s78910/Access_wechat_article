from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

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
    range_count: int = 0
    decisions: tuple[dict[str, Any], ...] = ()


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
        trace: Callable[[dict[str, Any]], None] | None = None,
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
        self._trace = trace
        self._sleep = sleep
        self._monotonic = monotonic

        self._processed_targets: list[ArticleTarget] = []
        self._overlap_alias_targets: list[ArticleTarget] = []
        self._visible_snapshot: list[ArticleTarget] = []
        self._snapshot_loaded = False
        self._snapshot_created_at = 0.0
        self._snapshot_home_key: tuple[int, tuple[int, int, int, int]] | None = None
        self._visible_signature: tuple[str, ...] = ()
        self._viewport_loading = False
        self._last_traced_viewport_key: tuple[Any, ...] | None = None

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
        self._last_traced_viewport_key = None

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
        if self._target_was_processed(target):
            return
        # 保留本次任务内的语义标记，供滚动后识别标题被裁切的同一篇文章。
        self._processed_targets.append(target)

    def refresh_target(
        self,
        home_window: WindowInfo,
        target: ArticleTarget,
    ) -> ArticleTarget:
        # 候选坐标只代表上一次 UI 树快照；点击前必须重新读取当前位置。
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
        duration_seconds = max(0.0, self._monotonic() - started_at)
        self._scan_duration_seconds += duration_seconds
        self._scan_count += 1
        self._visible_snapshot = visible
        self._snapshot_loaded = True
        self._snapshot_created_at = self._monotonic()
        self._snapshot_home_key = (home_window.handle, home_window.rect)
        self._visible_signature = observation.visible_signature
        self._viewport_loading = observation.loading
        self._trace_viewport_read(
            observation,
            visible=visible,
            duration_seconds=duration_seconds,
        )
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
                signature = self._identity_text_signature(list(targets))
            return _ReaderViewport(
                targets=targets,
                visible_signature=signature,
                loading=bool(getattr(value, "loading", False)),
                range_count=max(0, int(getattr(value, "range_count", 0) or 0)),
                decisions=tuple(getattr(value, "decisions", ()) or ()),
            )

        targets = tuple(
            self._reader.read(home_window, account_name=self._account_name)
        )
        return _ReaderViewport(
            targets=targets,
            visible_signature=self._identity_text_signature(list(targets)),
            loading=False,
        )

    def _trace_viewport_read(
        self,
        observation: _ReaderViewport,
        *,
        visible: list[ArticleTarget],
        duration_seconds: float,
    ) -> None:
        trace_key = (
            observation.visible_signature,
            self._content_signature(visible),
            observation.loading,
            repr(observation.decisions),
        )
        if trace_key == self._last_traced_viewport_key:
            return
        self._last_traced_viewport_key = trace_key
        discarded_count = sum(
            1
            for decision in observation.decisions
            if str(decision.get("status", "")) == "discarded"
        )
        self._emit_trace(
            {
                "event": "viewport-read",
                "status": "loading" if observation.loading else "success",
                "message": (
                    f"第 {self._scan_count} 次页面读取完成："
                    f"识别 {len(visible)} 条，丢弃 {discarded_count} 条"
                ),
                "details": {
                    "scanCount": self._scan_count,
                    "rangeCount": observation.range_count,
                    "targetCount": len(visible),
                    "discardedCount": discarded_count,
                    "loading": observation.loading,
                    "durationSeconds": round(duration_seconds, 3),
                },
                "decisions": [dict(item) for item in observation.decisions],
            }
        )

    def _scroll_until_candidate(self, home_window: WindowInfo) -> ArticleTarget | None:
        before_content = self._content_signature(self._visible_snapshot)
        before_visible = self._visible_signature
        before_targets = self._processed_visible_targets(self._visible_snapshot)
        bounce_used = 0

        for _attempt in range(self._max_scroll_attempts):
            if not self._send_scroll(home_window, direction="down", wheel_steps=None):
                return None
            self._scroll_down_count += 1
            status, candidate = self._wait_for_scroll_result(
                home_window,
                before_content=before_content,
                before_visible=before_visible,
                before_targets=before_targets,
            )
            if candidate is not None:
                return candidate
            if status == "unstable":
                # 当前视口没有形成可信快照时停止继续下滚，避免越过尚未识别的文章。
                return None

            after_content = self._content_signature(self._visible_snapshot)
            after_visible = self._visible_signature
            if status in {"unchanged", "loading-timeout"}:
                # 普通无变化只回弹一次；懒加载超时则继续使用剩余回弹次数，
                # 避免页面已有视觉内容但 UIA 树仍停留在过渡快照时直接结束。
                while self._bounce_enabled and bounce_used < self._bounce_attempts:
                    bounce_used += 1
                    bounce_status, candidate = self._bounce_for_lazy_load(home_window)
                    if candidate is not None:
                        return candidate
                    status = bounce_status
                    if status == "unstable":
                        return None
                    after_content = self._content_signature(self._visible_snapshot)
                    after_visible = self._visible_signature
                    if status != "loading-timeout":
                        break

                if status == "loading-timeout":
                    return None
                after_content = self._content_signature(self._visible_snapshot)
                after_visible = self._visible_signature

            before_content = after_content
            before_visible = after_visible
            before_targets = self._processed_visible_targets(self._visible_snapshot)
        return None

    def _wait_for_scroll_result(
        self,
        home_window: WindowInfo,
        *,
        before_content: tuple[tuple[str, str], ...],
        before_visible: tuple[str, ...],
        before_targets: tuple[ArticleTarget, ...],
    ) -> tuple[str, ArticleTarget | None]:
        self._wait(self._scroll_wait_seconds)
        started_at = self._monotonic()
        interval = self._scroll_probe_interval_seconds
        last_candidate_signature: tuple[str, str] | None = None
        stable_candidate_count = 0
        last_observation_signature: tuple[
            tuple[tuple[str, str], ...],
            tuple[str, ...],
        ] | None = None
        stable_observation_count = 0
        page_changed = False
        probe_count = 0
        loading_observed = False

        def finish(
            result: str,
            candidate: ArticleTarget | None = None,
        ) -> tuple[str, ArticleTarget | None]:
            messages = {
                "candidate": "页面变化检测完成，已发现稳定的新文章",
                "changed": "页面变化检测完成，页面已变化但暂未发现新文章",
                "unchanged": "页面变化检测完成，页面没有变化",
                "unstable": "页面变化检测结束，页面未形成稳定快照",
                "loading-timeout": "懒加载等待超时，准备执行回弹滚动",
            }
            self._emit_trace(
                {
                    "event": "scroll-probe",
                    "status": "success" if result in {"candidate", "changed"} else result,
                    "message": messages[result],
                    "details": {
                        "result": result,
                        "probeCount": probe_count,
                        "durationSeconds": round(
                            max(0.0, self._monotonic() - started_at),
                            3,
                        ),
                        "pageChanged": page_changed,
                        "loadingObserved": loading_observed,
                    },
                }
            )
            return result, candidate

        while True:
            visible = self._refresh_snapshot(home_window)
            self._scroll_probe_count += 1
            probe_count += 1
            after_content = self._content_signature(visible)
            changed = (
                after_content != before_content
                or self._visible_signature != before_visible
            )
            page_changed = page_changed or changed
            elapsed = max(0.0, self._monotonic() - started_at)

            observation_signature = (after_content, self._visible_signature)
            if observation_signature == last_observation_signature:
                stable_observation_count += 1
            else:
                last_observation_signature = observation_signature
                stable_observation_count = 1

            if self._viewport_loading:
                self._loading_wait_count += 1
                loading_observed = True

            candidate = self._first_unprocessed_after_anchor(
                visible,
                before_targets=before_targets,
            )
            if candidate is not None:
                candidate_signature = self._candidate_stability_signature(candidate)
                if candidate_signature == last_candidate_signature:
                    stable_candidate_count += 1
                else:
                    last_candidate_signature = candidate_signature
                    stable_candidate_count = 1
                if stable_candidate_count >= 2:
                    self._cache_candidate_count += 1
                    return finish("candidate", candidate)

                # UIA 单次读取可能接近一秒；变化中的视口使用懒加载上限，
                # 保证标题过渡帧之后仍有机会得到第二次可信观察。
                transition_limit = max(
                    self._lazy_load_timeout_seconds,
                    self._scroll_probe_interval_seconds,
                )
                if elapsed >= transition_limit:
                    return finish("unstable")
                remaining = transition_limit - elapsed
                self._wait(min(interval, remaining))
                interval = min(
                    self._scroll_probe_max_interval_seconds,
                    interval * 1.5,
                )
                continue
            last_candidate_signature = None
            stable_candidate_count = 0

            if self._viewport_loading:
                if elapsed >= self._lazy_load_timeout_seconds:
                    return finish("loading-timeout")
                remaining = self._lazy_load_timeout_seconds - elapsed
                self._wait(min(interval, remaining))
                interval = min(
                    self._scroll_probe_max_interval_seconds,
                    interval * 1.5,
                )
                continue

            if changed:
                if visible and stable_observation_count >= 2:
                    # 页面已经稳定，但只有处理过的重叠文章，可以安全进入下一轮滚动。
                    return finish("changed")
                transition_limit = max(
                    self._lazy_load_timeout_seconds,
                    self._scroll_probe_interval_seconds,
                )
                if elapsed >= transition_limit:
                    if not visible:
                        self._interference_view_count += 1
                    return finish("unstable")
                remaining = transition_limit - elapsed
                self._wait(min(interval, remaining))
                interval = min(
                    self._scroll_probe_max_interval_seconds,
                    interval * 1.5,
                )
                continue

            if page_changed:
                # 页面曾经变化但又回到旧签名，继续观察到变化视口稳定或超时。
                transition_limit = max(
                    self._lazy_load_timeout_seconds,
                    self._scroll_probe_interval_seconds,
                )
                if elapsed >= transition_limit:
                    return finish("unstable")
                remaining = transition_limit - elapsed
                self._wait(min(interval, remaining))
                interval = min(
                    self._scroll_probe_max_interval_seconds,
                    interval * 1.5,
                )
                continue

            unchanged_limit = min(
                self._scroll_settle_timeout_seconds,
                self._unchanged_before_bounce_seconds,
            )
            if elapsed >= unchanged_limit:
                return finish("unchanged")
            remaining = unchanged_limit - elapsed
            self._wait(min(interval, remaining))
            interval = min(
                self._scroll_probe_max_interval_seconds,
                interval * 1.5,
            )

    def _bounce_for_lazy_load(
        self,
        home_window: WindowInfo,
    ) -> tuple[str, ArticleTarget | None]:
        if not self._send_scroll(
            home_window,
            direction="up",
            wheel_steps=self._bounce_up_steps,
        ):
            return "unstable", None
        self._scroll_up_count += 1
        self._wait(self._bounce_pause_seconds)

        if not self._send_scroll(
            home_window,
            direction="down",
            wheel_steps=self._bounce_down_steps,
        ):
            return "unstable", None
        self._scroll_down_count += 1
        self._bounce_count += 1
        status, candidate = self._wait_for_scroll_result(
            home_window,
            before_content=self._content_signature(self._visible_snapshot),
            before_visible=self._visible_signature,
            before_targets=self._processed_visible_targets(self._visible_snapshot),
        )
        return status, candidate

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
            actual_steps = (
                max(1, int(wheel_steps))
                if wheel_steps is not None
                else max(1, int(getattr(self._scroller, "wheel_steps", 1) or 1))
            )
            succeeded = bool(
                scroll(
                    home_window,
                    visible_targets=list(self._visible_snapshot),
                    direction=direction,
                    wheel_steps=wheel_steps,
                )
            )
            self._trace_scroll_dispatch(
                direction=direction,
                wheel_steps=actual_steps,
                succeeded=succeeded,
            )
            return succeeded
        if direction == "down":
            legacy = getattr(self._scroller, "scroll_down", None)
            if callable(legacy):
                succeeded = bool(
                    legacy(
                        home_window,
                        visible_targets=list(self._visible_snapshot),
                    )
                )
                self._trace_scroll_dispatch(
                    direction=direction,
                    wheel_steps=max(
                        1,
                        int(getattr(self._scroller, "wheel_steps", 1) or 1),
                    ),
                    succeeded=succeeded,
                )
                return succeeded
        return False

    def _trace_scroll_dispatch(
        self,
        *,
        direction: str,
        wheel_steps: int,
        succeeded: bool,
    ) -> None:
        direction_label = "向上" if direction == "up" else "向下"
        self._emit_trace(
            {
                "event": "scroll-dispatch",
                "status": "success" if succeeded else "failed",
                "message": (
                    f"{direction_label}滚动 {wheel_steps} 步"
                    f"{'已发送' if succeeded else '发送失败'}"
                ),
                "details": {
                    "direction": direction,
                    "wheelSteps": wheel_steps,
                    "succeeded": succeeded,
                },
            }
        )

    def _emit_trace(self, event: dict[str, Any]) -> None:
        if self._trace is None:
            return
        try:
            self._trace(event)
        except Exception:
            # 诊断展示失败不能中断主页候选读取和主采集流程。
            return

    def _wait(self, seconds: float) -> None:
        if seconds > 0:
            self._sleep(seconds)
            self._scroll_wait_duration_seconds += seconds

    def _first_unprocessed(self, visible: list[ArticleTarget]) -> ArticleTarget | None:
        for target in visible:
            if not self._target_was_processed(target):
                return target
        return None

    def _first_unprocessed_after_anchor(
        self,
        visible: list[ArticleTarget],
        *,
        before_targets: tuple[ArticleTarget, ...],
    ) -> ArticleTarget | None:
        """用上一视口末篇作为锚点，只接收锚点之后的新文章。"""

        start_index = 0
        if before_targets:
            anchor = before_targets[-1]
            anchor_indices = [
                index
                for index, target in enumerate(visible)
                if self._anchor_matches(target, anchor)
            ]
            if anchor_indices:
                start_index = anchor_indices[-1] + 1
            else:
                overlap_indices = [
                    index
                    for index, target in enumerate(visible)
                    if any(
                        self._anchor_matches(target, previous)
                        for previous in before_targets
                    )
                ]
                if overlap_indices:
                    start_index = overlap_indices[-1] + 1

            for target in visible[:start_index]:
                if any(
                    self._anchor_matches(target, previous)
                    for previous in before_targets
                ) and not self._target_was_processed(target):
                    self._overlap_alias_targets.append(target)

        return self._first_unprocessed(visible[start_index:])

    def _processed_visible_targets(
        self,
        visible: list[ArticleTarget],
    ) -> tuple[ArticleTarget, ...]:
        return tuple(target for target in visible if self._target_was_processed(target))

    def _target_was_processed(self, target: ArticleTarget) -> bool:
        return any(
            self._same_article(target, processed)
            for processed in (
                *self._processed_targets,
                *self._overlap_alias_targets,
            )
        )

    @classmethod
    def _same_article(cls, left: ArticleTarget, right: ArticleTarget) -> bool:
        left_title, left_date = cls._article_identity_signature(left)
        right_title, right_date = cls._article_identity_signature(right)
        return bool(
            left_title
            and right_title
            and left_date == right_date
            and left_title == right_title
        )

    @classmethod
    def _anchor_matches(cls, left: ArticleTarget, right: ArticleTarget) -> bool:
        """相邻视口锚点允许标题被裁切，不能用于全局已处理查重。"""

        left_title, left_date = cls._article_identity_signature(left)
        right_title, right_date = cls._article_identity_signature(right)
        if not left_title or not right_title or left_date != right_date:
            return False
        if left_title == right_title:
            return True

        left_compact = cls._compact_title(left_title)
        right_compact = cls._compact_title(right_title)
        return (
            min(len(left_compact), len(right_compact)) >= 4
            and (left_compact in right_compact or right_compact in left_compact)
        )

    @staticmethod
    def _compact_title(value: str) -> str:
        return "".join(character for character in value if character.isalnum())

    @staticmethod
    def _article_identity_signature(target: ArticleTarget) -> tuple[str, str]:
        """文章身份只使用 UI 树标题原文和标准日期，不包含临时坐标。"""

        title = normalize_window_text(target.raw_title or target.title).casefold()
        published_date = normalize_window_text(
            target.published_date or target.date_text
        )
        return title, published_date

    @classmethod
    def _candidate_stability_signature(
        cls,
        target: ArticleTarget,
    ) -> tuple[str, str]:
        return cls._article_identity_signature(target)

    @classmethod
    def _resolve_target(
        cls,
        visible: list[ArticleTarget],
        target: ArticleTarget,
    ) -> ArticleTarget | None:
        identity_matches = [
            item for item in visible if cls._same_article(item, target)
        ]
        if len(identity_matches) == 1:
            return identity_matches[0]
        if len(identity_matches) > 1:
            raise TargetRefreshError(
                f"点击前发现多个同标题同日期候选，无法安全确认：{target.title}"
            )
        anchor_matches = [
            item for item in visible if cls._anchor_matches(item, target)
        ]
        if len(anchor_matches) == 1:
            return anchor_matches[0]
        return None

    @classmethod
    def _content_signature(
        cls,
        visible: list[ArticleTarget],
    ) -> tuple[tuple[str, str], ...]:
        return tuple(
            cls._article_identity_signature(item)
            for item in visible
        )

    @classmethod
    def _identity_text_signature(
        cls,
        visible: list[ArticleTarget],
    ) -> tuple[str, ...]:
        return tuple(
            "\n".join(cls._article_identity_signature(item))
            for item in visible
        )


__all__ = ["HomeArticleCursor", "TargetRefreshError"]
