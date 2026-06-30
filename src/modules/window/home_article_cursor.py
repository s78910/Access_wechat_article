from __future__ import annotations

import ctypes
import platform
import time
from dataclasses import dataclass
from typing import Any, Callable

from src.modules.window.article_clicker import ArticleClickTarget, collect_article_click_targets
from src.modules.window.home_window_focus_guard import (
    ensure_home_window_readable as default_ensure_home_window_readable,
    resolve_focus_recover_attempts,
)


WM_MOUSEWHEEL = 0x020A
WHEEL_DELTA = 120
DEFAULT_SCROLL_LOAD_TIMEOUT_SECONDS = 1.0
DEFAULT_SCROLL_POLL_INTERVAL_SECONDS = 0.15
DEFAULT_SCROLL_PAUSE_SECONDS = 0.35
DEFAULT_SCROLL_BOUNCE_ATTEMPTS = 1
DEFAULT_SCROLL_BOUNCE_RATIO = 0.5
DEFAULT_SCROLL_BOUNCE_PAUSE_SECONDS = 0.18
DEFAULT_SCROLL_EMPTY_LIMIT = 5
DEFAULT_FAST_SKIP_SCROLL_DELTA_RATIO = 1.35
DEFAULT_FAST_SKIP_LOAD_TIMEOUT_SECONDS = 0.45
DEFAULT_FAST_SKIP_PAUSE_SECONDS = 0.05

TargetCollector = Callable[..., list[ArticleClickTarget]]
HomeScroller = Callable[..., dict[str, Any]]
HomeFocusGuard = Callable[[Any, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class HomeArticleCandidate:
    """主页文章候选项；article_index 是当前可见列表里的点击序号。"""

    title: str
    article_index: int
    rect: tuple[int, int, int, int]
    hwnd: int


class HomeArticleCursor:
    """按“当前屏候选 -> 滚动 -> 下一屏候选”的方式顺序产出文章。"""

    def __init__(
        self,
        *,
        config: dict[str, Any] | None = None,
        home_window: Any | None = None,
        collect_targets: TargetCollector = collect_article_click_targets,
        scroll_home: HomeScroller | None = None,
        ensure_home_window_readable: HomeFocusGuard | None = default_ensure_home_window_readable,
    ) -> None:
        self.config = config or {}
        self.home_window = home_window
        self.collect_targets = collect_targets
        self.scroll_home = scroll_home or scroll_wechat_home_articles
        self.ensure_home_window_readable = ensure_home_window_readable
        self._visible: list[HomeArticleCandidate] = []
        self._position = 0
        self._loaded = False
        self._seen_signatures: set[str] = set()
        self._last_screen_signature: tuple[str, ...] = ()
        self._unchanged_scrolls = 0
        self._empty_scrolls = 0
        self._last_stop_reason = ""
        self._fast_skip_next_scroll = False

    @property
    def has_visible_candidates(self) -> bool:
        """当前游标最近一次是否读到过可见文章候选，用于区分锁屏不可读和列表已到底。"""
        return bool(self._visible)

    @property
    def last_stop_reason(self) -> str:
        """最近一次无法继续产出候选的原因，供主流程判断是否需要等待解锁恢复。"""
        return self._last_stop_reason

    @property
    def visible_candidates(self) -> list[HomeArticleCandidate]:
        """返回最近一次读取到的当前屏候选副本，供点击前一致性校验使用。"""
        return list(self._visible)

    def invalidate(self) -> None:
        """让下一次读取重新扫描主页窗口，避免锁屏/解锁或关闭详情页后继续使用旧坐标。"""
        self._loaded = False
        self._visible = []
        self._position = 0
        self._last_stop_reason = ""

    def refresh_visible_candidates(self) -> bool:
        """重新读取当前屏候选但不消费候选，供采集前健康检查使用。"""
        self.invalidate()
        self._load_visible_candidates()
        return bool(self._visible)

    def skip_visible_candidates(self, titles: list[str] | None = None) -> None:
        """当前可见屏无需点击时，把这些标题标记为已处理，让下一次读取进入滚动。"""
        title_set = {_normalize_title(title) for title in (titles or []) if str(title or "").strip()}
        for candidate in self._visible:
            signature = self._candidate_signature(candidate)
            if title_set and signature not in title_set:
                continue
            self._seen_signatures.add(signature)
        self._position = len(self._visible)
        if _resolve_bool_config(self.config, "homepage_fast_skip_saved_enabled", True):
            # 当前屏都是已保存文章时，下次滚动使用快进参数，减少在旧内容上停留的时间。
            self._fast_skip_next_scroll = True

    def next_candidate(self) -> HomeArticleCandidate | None:
        while True:
            if not self._loaded:
                self._load_visible_candidates()

            while self._position < len(self._visible):
                candidate = self._visible[self._position]
                self._position += 1
                signature = self._candidate_signature(candidate)
                if signature in self._seen_signatures:
                    continue
                self._seen_signatures.add(signature)
                self._last_stop_reason = ""
                return candidate

            if not self._scroll_and_reload():
                return None

    def _load_visible_candidates(self) -> None:
        targets = self._collect_targets_with_focus_recovery()
        visible: list[HomeArticleCandidate] = []
        for target in targets:
            candidate = _candidate_from_click_target(target)
            if candidate is not None:
                visible.append(candidate)
        visible.sort(key=lambda candidate: (candidate.rect[1], candidate.rect[0], candidate.rect[3], candidate.rect[2]))
        self._visible = [
            HomeArticleCandidate(
                title=candidate.title,
                article_index=index,
                rect=candidate.rect,
                hwnd=candidate.hwnd,
            )
            for index, candidate in enumerate(visible, 1)
        ]
        self._position = 0
        self._loaded = True

    def _collect_targets_with_focus_recovery(self) -> list[ArticleClickTarget]:
        targets = self._collect_targets_once()
        if targets:
            return targets

        recover = self.ensure_home_window_readable
        if not callable(recover):
            return targets

        for _attempt_index in range(resolve_focus_recover_attempts(self.config)):
            recover(self.home_window, self.config)
            targets = self._collect_targets_once()
            if targets:
                return targets
        return targets

    def _collect_targets_once(self) -> list[ArticleClickTarget]:
        return self.collect_targets(
            self.home_window,
            max_depth=int(self.config.get("homepage_max_depth", 12)),
            max_nodes=int(self.config.get("homepage_max_nodes", 5000)),
        )

    def _scroll_and_reload(self) -> bool:
        # 当前屏候选的坐标能帮助把滚轮消息投递到真实文章列表区域，而不是只发给外层窗口。
        current_visible = list(self._visible)
        before = self._last_screen_signature or self._screen_signature(self._visible)
        fast_skip = bool(self._fast_skip_next_scroll)
        self._fast_skip_next_scroll = False
        down_delta_ratio = self._resolve_scroll_delta_ratio(fast_skip=fast_skip)
        result = self._send_scroll(current_visible, direction="down", delta_ratio=down_delta_ratio)
        if result.get("ok") is False:
            self._last_stop_reason = "scroll_failed"
            return False

        after = self._load_visible_candidates_until_changed(before, fast_skip=fast_skip)
        if not self._has_new_visible_screen(before, after):
            bounced_after = self._try_bounce_scroll_for_loading(before, fast_skip=fast_skip)
            if bounced_after is not None:
                after = bounced_after
            if self._last_stop_reason == "scroll_failed":
                return False

        self._last_screen_signature = after
        if after == before:
            self._unchanged_scrolls += 1
        else:
            self._unchanged_scrolls = 0
        # 微信主页滚动和 UIA 树刷新不是严格同步的；同一屏短暂不变时继续尝试，避免过早结束 10 篇任务。
        unchanged_limit = max(1, int(self.config.get("homepage_scroll_unchanged_limit", 5)))
        if not self._visible:
            self._empty_scrolls += 1
            empty_limit = max(
                1,
                _safe_int(
                    self.config.get("homepage_scroll_empty_limit", DEFAULT_SCROLL_EMPTY_LIMIT),
                    DEFAULT_SCROLL_EMPTY_LIMIT,
                ),
            )
            if self._empty_scrolls >= empty_limit:
                self._last_stop_reason = "no_visible_candidates"
                return False
            self._last_stop_reason = ""
            return True
        self._empty_scrolls = 0
        if self._unchanged_scrolls >= unchanged_limit:
            self._last_stop_reason = "unchanged_after_scroll"
            return False
        self._last_stop_reason = ""
        return True

    def _resolve_scroll_delta_ratio(self, *, fast_skip: bool) -> float:
        if not fast_skip:
            return 1.0
        return _resolve_float_config(
            self.config,
            "homepage_fast_skip_scroll_delta_ratio",
            DEFAULT_FAST_SKIP_SCROLL_DELTA_RATIO,
        )

    def _send_scroll(
        self,
        visible_candidates: list[HomeArticleCandidate],
        *,
        direction: str,
        delta_ratio: float,
    ) -> dict[str, Any]:
        scroll_config = dict(self.config)
        scroll_config["homepage_scroll_direction"] = direction
        scroll_config["homepage_scroll_delta_ratio"] = max(0.01, float(delta_ratio))
        return self.scroll_home(self.home_window, scroll_config, visible_candidates=visible_candidates)

    def _load_visible_candidates_until_changed(self, before: tuple[str, ...], *, fast_skip: bool = False) -> tuple[str, ...]:
        if fast_skip:
            pause_seconds = _resolve_float_config(
                self.config,
                "homepage_fast_skip_scroll_pause_seconds",
                DEFAULT_FAST_SKIP_PAUSE_SECONDS,
            )
        else:
            pause_seconds = _resolve_float_config(self.config, "homepage_scroll_pause_seconds", DEFAULT_SCROLL_PAUSE_SECONDS)
        if pause_seconds > 0:
            time.sleep(pause_seconds)

        if fast_skip:
            timeout_seconds = _resolve_float_config(
                self.config,
                "homepage_fast_skip_load_timeout_seconds",
                DEFAULT_FAST_SKIP_LOAD_TIMEOUT_SECONDS,
            )
        else:
            timeout_seconds = _resolve_float_config(
                self.config,
                "homepage_scroll_load_timeout_seconds",
                DEFAULT_SCROLL_LOAD_TIMEOUT_SECONDS,
            )
        poll_interval = _resolve_float_config(
            self.config,
            "homepage_scroll_poll_interval_seconds",
            DEFAULT_SCROLL_POLL_INTERVAL_SECONDS,
        )
        deadline = time.monotonic() + timeout_seconds

        while True:
            self._loaded = False
            self._load_visible_candidates()
            after = self._screen_signature(self._visible)
            if self._has_new_visible_screen(before, after):
                return after
            if timeout_seconds <= 0 or time.monotonic() >= deadline:
                return after
            sleep_seconds = min(max(poll_interval, 0.01), max(0.0, deadline - time.monotonic()))
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

    def _try_bounce_scroll_for_loading(self, before: tuple[str, ...], *, fast_skip: bool = False) -> tuple[str, ...] | None:
        if not _resolve_bool_config(self.config, "homepage_scroll_bounce_enabled", True):
            return None

        attempts = max(
            0,
            _safe_int(
                self.config.get("homepage_scroll_bounce_attempts", DEFAULT_SCROLL_BOUNCE_ATTEMPTS),
                DEFAULT_SCROLL_BOUNCE_ATTEMPTS,
            ),
        )
        if attempts <= 0:
            return None

        bounce_ratio = _resolve_float_config(self.config, "homepage_scroll_bounce_ratio", DEFAULT_SCROLL_BOUNCE_RATIO)
        bounce_pause = _resolve_float_config(
            self.config,
            "homepage_scroll_bounce_pause_seconds",
            DEFAULT_SCROLL_BOUNCE_PAUSE_SECONDS,
        )
        after = self._screen_signature(self._visible)
        down_delta_ratio = self._resolve_scroll_delta_ratio(fast_skip=fast_skip)
        for _attempt_index in range(attempts):
            current_visible = list(self._visible)
            up_result = self._send_scroll(current_visible, direction="up", delta_ratio=bounce_ratio)
            if up_result.get("ok") is False:
                self._last_stop_reason = "scroll_failed"
                return after
            if bounce_pause > 0:
                time.sleep(bounce_pause)

            down_result = self._send_scroll(current_visible, direction="down", delta_ratio=down_delta_ratio)
            if down_result.get("ok") is False:
                self._last_stop_reason = "scroll_failed"
                return after
            after = self._load_visible_candidates_until_changed(before, fast_skip=fast_skip)
            if self._has_new_visible_screen(before, after):
                return after
        return after

    def _has_new_visible_screen(self, before: tuple[str, ...], after: tuple[str, ...]) -> bool:
        return bool(self._visible) and after != before

    @staticmethod
    def _screen_signature(candidates: list[HomeArticleCandidate]) -> tuple[str, ...]:
        return tuple(_normalize_title(candidate.title) for candidate in candidates)

    @staticmethod
    def _candidate_signature(candidate: HomeArticleCandidate) -> str:
        return _normalize_title(candidate.title)


def scroll_wechat_home_articles(
    home_window: Any,
    config: dict[str, Any] | None = None,
    *,
    visible_candidates: list[HomeArticleCandidate] | None = None,
) -> dict[str, Any]:
    """向下滚动公众号主页列表；只滚动主页窗口，不触发文章点击。"""
    if home_window is None:
        return {"ok": False, "reason": "wechat_home_window_not_found"}
    if platform.system() != "Windows":
        return {"ok": False, "reason": "scroll_only_supported_on_windows"}

    config = config or {}
    hwnd = _safe_int(getattr(home_window, "NativeWindowHandle", 0))
    if hwnd <= 0:
        return {"ok": False, "reason": "wechat_home_hwnd_empty"}

    user32 = ctypes.windll.user32
    direction = str(config.get("homepage_scroll_direction", "down")).lower()
    base_delta = abs(_safe_int(config.get("homepage_scroll_delta", WHEEL_DELTA * 5), WHEEL_DELTA * 5) or WHEEL_DELTA * 5)
    delta_ratio = max(0.01, _safe_float(config.get("homepage_scroll_delta_ratio", 1.0), 1.0))
    wheel_delta = max(1, int(round(base_delta * delta_ratio)))
    if direction != "up":
        wheel_delta = -wheel_delta
    repeat = max(1, _safe_int(config.get("homepage_scroll_repeat", 1), 1))
    target_hwnd, screen_point, client_point = _resolve_scroll_message_target(
        user32,
        hwnd,
        visible_candidates or [],
        rect_to_tuple(_safe_get(home_window, "BoundingRectangle", None)),
    )
    # WM_MOUSEWHEEL 的 lParam 使用屏幕坐标；client_point 只用于日志和诊断。
    lparam = _make_lparam(screen_point[0], screen_point[1]) if screen_point else 0
    for index in range(repeat):
        user32.PostMessageW(int(target_hwnd), WM_MOUSEWHEEL, _make_wparam(wheel_delta), lparam)
        if index + 1 < repeat:
            time.sleep(0.08)
    return {
        "ok": True,
        "method": "post_message_mouse_wheel",
        "hwnd": hwnd,
        "target_hwnd": int(target_hwnd),
        "screen_point": list(screen_point) if screen_point else [],
        "client_point": list(client_point) if client_point else [],
        "wheel_delta": wheel_delta,
        "direction": direction,
        "delta_ratio": delta_ratio,
    }


def _normalize_title(value: str) -> str:
    return " ".join(str(value or "").split()).lower()


def _candidate_from_click_target(target: ArticleClickTarget) -> HomeArticleCandidate | None:
    title = str(_safe_get(target, "title", "") or "").strip()
    rect = rect_to_tuple(_safe_get(target, "rect", None))
    hwnd = _safe_int(_safe_get(target, "hwnd", 0))
    if not title or not _valid_rect(rect) or hwnd <= 0:
        return None
    return HomeArticleCandidate(title=title, article_index=0, rect=rect, hwnd=hwnd)


def _make_wparam(delta: int) -> int:
    return (int(delta) & 0xFFFF) << 16


def _make_lparam(x: int, y: int) -> int:
    return (int(y) & 0xFFFF) << 16 | (int(x) & 0xFFFF)


def _resolve_scroll_message_target(
    user32: Any,
    parent_hwnd: int,
    visible_candidates: list[HomeArticleCandidate],
    home_rect: tuple[int, int, int, int],
) -> tuple[int, tuple[int, int] | None, tuple[int, int] | None]:
    screen_point = _resolve_scroll_screen_point(visible_candidates, home_rect)
    if not screen_point:
        return parent_hwnd, None, None

    target_hwnd = _find_child_hwnd_containing_point(user32, parent_hwnd, screen_point[0], screen_point[1]) or parent_hwnd
    point = POINT(int(screen_point[0]), int(screen_point[1]))
    if not user32.ScreenToClient(int(target_hwnd), ctypes.byref(point)):
        return parent_hwnd, screen_point, None
    return int(target_hwnd), screen_point, (int(point.x), int(point.y))


def _resolve_scroll_screen_point(
    visible_candidates: list[HomeArticleCandidate],
    home_rect: tuple[int, int, int, int],
) -> tuple[int, int] | None:
    valid_rects = [candidate.rect for candidate in visible_candidates if _valid_rect(candidate.rect)]
    if valid_rects:
        left = min(rect[0] for rect in valid_rects)
        top = min(rect[1] for rect in valid_rects)
        right = max(rect[2] for rect in valid_rects)
        bottom = max(rect[3] for rect in valid_rects)
        return ((left + right) // 2, (top + bottom) // 2)

    if _valid_rect(home_rect):
        left, top, right, bottom = home_rect
        return ((left + right) // 2, top + int((bottom - top) * 0.68))
    return None


def _find_child_hwnd_containing_point(user32: Any, parent_hwnd: int, x: int, y: int) -> int:
    if platform.system() != "Windows" or parent_hwnd <= 0:
        return 0

    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    matches: list[tuple[int, int]] = []

    def callback(child_hwnd, _lparam):
        child = int(child_hwnd)
        rect = RECT()
        try:
            visible = bool(user32.IsWindowVisible(child))
            has_rect = bool(user32.GetWindowRect(child, ctypes.byref(rect)))
        except Exception:
            return True

        if not visible or not has_rect:
            return True

        left, top, right, bottom = int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
        if right <= left or bottom <= top:
            return True
        if left <= int(x) < right and top <= int(y) < bottom:
            matches.append(((right - left) * (bottom - top), child))
        return True

    try:
        user32.EnumChildWindows(int(parent_hwnd), enum_proc(callback), 0)
    except Exception:
        return 0

    if not matches:
        return 0
    matches.sort(key=lambda item: item[0])
    return matches[0][1]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def rect_to_tuple(rect: Any) -> tuple[int, int, int, int]:
    if isinstance(rect, (list, tuple)) and len(rect) == 4:
        return tuple(int(item) for item in rect)

    for names in (("left", "top", "right", "bottom"), ("Left", "Top", "Right", "Bottom")):
        values = [_safe_get(rect, name, None) for name in names]
        if all(value is not None for value in values):
            return tuple(int(value) for value in values)

    return (0, 0, 0, 0)


def _valid_rect(rect: tuple[int, int, int, int]) -> bool:
    left, top, right, bottom = rect
    return right > left and bottom > top


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return int(default)
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _resolve_float_config(config: dict[str, Any], key: str, default: float) -> float:
    return max(0.0, _safe_float(config.get(key, default), default))


def _resolve_bool_config(config: dict[str, Any], key: str, default: bool) -> bool:
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _safe_get(obj: Any, attr_name: str, default: Any = "") -> Any:
    try:
        return getattr(obj, attr_name)
    except Exception:
        return default


__all__ = ["HomeArticleCandidate", "HomeArticleCursor", "scroll_wechat_home_articles"]
