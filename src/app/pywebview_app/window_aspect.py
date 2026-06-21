from __future__ import annotations

from dataclasses import dataclass
from threading import Lock


Size = tuple[int, int]


@dataclass
class AspectResizeState:
    previous_width: int
    previous_height: int
    is_adjusting: bool = False


def calculate_aspect_size(
    width: int,
    height: int,
    previous_width: int,
    previous_height: int,
    ratio: float,
    min_size: Size,
    tolerance: int = 2,
) -> Size:
    """根据拖拽方向，把外层窗口尺寸修正到固定宽高比。"""
    min_width, min_height = min_size
    safe_width = max(width, min_width)
    safe_height = max(height, min_height)

    expected_height = round(safe_width / ratio)
    expected_width = round(safe_height * ratio)

    if abs(expected_height - safe_height) <= tolerance:
        return safe_width, safe_height

    width_delta = abs(safe_width - previous_width)
    height_delta = abs(safe_height - previous_height)

    if width_delta >= height_delta:
        return safe_width, max(expected_height, min_height)

    return max(expected_width, min_width), safe_height


def bind_aspect_ratio(window, ratio: float, min_size: Size) -> None:
    """监听 pywebview 外层窗口尺寸变化，拖拽时保持固定宽高比。"""
    state = AspectResizeState(*min_size)
    lock = Lock()

    def handle_resized(width: int, height: int) -> None:
        with lock:
            if state.is_adjusting:
                state.is_adjusting = False
                state.previous_width, state.previous_height = width, height
                return

            next_width, next_height = calculate_aspect_size(
                width=width,
                height=height,
                previous_width=state.previous_width,
                previous_height=state.previous_height,
                ratio=ratio,
                min_size=min_size,
            )

            if (next_width, next_height) == (width, height):
                state.previous_width, state.previous_height = width, height
                return

            state.is_adjusting = True
            state.previous_width = next_width
            state.previous_height = next_height

        window.resize(next_width, next_height)

    window.events.resized += handle_resized
