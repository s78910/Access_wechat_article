from __future__ import annotations

import ctypes
import platform

from src.domain.models import ArticleTarget
from src.modules.window.window_models import WindowInfo


WM_MOUSEWHEEL = 0x020A
WHEEL_DELTA = 120


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class WechatHomeScroller:
    """向已确认的微信主页列表发送滚轮消息，不占用用户鼠标。"""

    def __init__(self, *, wheel_steps: int = 5) -> None:
        self._wheel_steps = max(1, int(wheel_steps))

    def scroll_down(
        self,
        home_window: WindowInfo,
        *,
        visible_targets: list[ArticleTarget],
    ) -> bool:
        return self.scroll(
            home_window,
            visible_targets=visible_targets,
            direction="down",
        )

    def scroll_up(
        self,
        home_window: WindowInfo,
        *,
        visible_targets: list[ArticleTarget],
    ) -> bool:
        return self.scroll(
            home_window,
            visible_targets=visible_targets,
            direction="up",
        )

    def scroll(
        self,
        home_window: WindowInfo,
        *,
        visible_targets: list[ArticleTarget],
        direction: str,
        wheel_steps: int | None = None,
    ) -> bool:
        if platform.system() != "Windows" or home_window.handle <= 0:
            return False
        normalized_direction = str(direction).strip().lower()
        if normalized_direction not in {"up", "down"}:
            raise ValueError(f"不支持的主页滚动方向：{direction}")
        _enable_per_monitor_dpi_awareness()
        x, y = _scroll_point(home_window, visible_targets)
        user32 = ctypes.windll.user32
        target_handle = int(user32.WindowFromPoint(_Point(x, y)) or home_window.handle)
        steps = self._wheel_steps if wheel_steps is None else max(1, int(wheel_steps))
        wheel_delta = WHEEL_DELTA * steps
        if normalized_direction == "down":
            wheel_delta = -wheel_delta
        return bool(
            user32.PostMessageW(
                target_handle,
                WM_MOUSEWHEEL,
                _make_wparam(wheel_delta),
                _make_lparam(x, y),
            )
        )


def _scroll_point(
    home_window: WindowInfo,
    visible_targets: list[ArticleTarget],
) -> tuple[int, int]:
    if visible_targets:
        # 点落在文章内容区域内，避免滚到微信左侧导航或顶部工具栏。
        middle = visible_targets[len(visible_targets) // 2]
        return int(middle.click_x), int(middle.click_y)
    left, top, right, bottom = home_window.rect
    return (left + right) // 2, top + max(1, (bottom - top) * 2 // 3)


def _enable_per_monitor_dpi_awareness() -> None:
    try:
        setter = getattr(ctypes.windll.user32, "SetThreadDpiAwarenessContext", None)
        if setter is not None:
            setter(ctypes.c_void_p(-4))
    except Exception:
        pass


def _make_wparam(delta: int) -> int:
    return (int(delta) & 0xFFFF) << 16


def _make_lparam(x: int, y: int) -> int:
    return (int(y) & 0xFFFF) << 16 | (int(x) & 0xFFFF)
