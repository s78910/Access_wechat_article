from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from src.app.pywebview_app.window_content_size import get_client_and_outer_size


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
    frame_size: Size = (0, 0),
    tolerance: int = 2,
) -> Size:
    """Correct the web content area to the target aspect ratio."""
    min_width, min_height = min_size
    safe_width = max(width, min_width)
    safe_height = max(height, min_height)
    frame_width, frame_height = frame_size
    client_width = max(1, safe_width - max(0, frame_width))
    client_height = max(1, safe_height - max(0, frame_height))

    expected_client_height = round(client_width / ratio)
    expected_client_width = round(client_height * ratio)

    if abs(expected_client_height - client_height) <= tolerance:
        return safe_width, safe_height

    width_delta = abs(safe_width - previous_width)
    height_delta = abs(safe_height - previous_height)

    if width_delta >= height_delta:
        expected_outer_height = expected_client_height + max(0, frame_height)
        return safe_width, max(expected_outer_height, min_height)

    expected_outer_width = expected_client_width + max(0, frame_width)
    return max(expected_outer_width, min_width), safe_height


def calculate_logical_frame_size(
    outer_size: Size,
    native_outer_size: Size,
    native_client_size: Size,
) -> Size:
    """Convert native frame pixels to pywebview logical resize pixels."""
    outer_width, outer_height = outer_size
    native_outer_width, native_outer_height = native_outer_size
    native_client_width, native_client_height = native_client_size

    scale_x = native_outer_width / outer_width if outer_width > 0 else 1
    scale_y = native_outer_height / outer_height if outer_height > 0 else 1
    frame_width = max(0, native_outer_width - native_client_width)
    frame_height = max(0, native_outer_height - native_client_height)

    logical_frame_width = round(frame_width / scale_x) if scale_x > 0 else frame_width
    logical_frame_height = round(frame_height / scale_y) if scale_y > 0 else frame_height
    return logical_frame_width, logical_frame_height


def calculate_outer_size_from_native(window, fallback_size: Size) -> Size:
    """Read current logical outer size from pywebview native window."""
    _client_size, outer_size = get_client_and_outer_size(window, fallback_size=fallback_size)
    native_window = getattr(window, "native", None)
    scale = float(getattr(native_window, "_scale", 1) or 1)
    if scale <= 0:
        scale = 1
    return round(outer_size[0] / scale), round(outer_size[1] / scale)


def bind_aspect_ratio(window, ratio: float, min_size: Size) -> None:
    """Keep the pywebview content area close to the target aspect ratio."""
    state = AspectResizeState(*min_size)
    lock = Lock()

    def correct_size(
        width: int,
        height: int,
        *,
        adjusting_event: bool = False,
        expect_resize_event: bool = True,
    ) -> None:
        with lock:
            if adjusting_event and state.is_adjusting:
                state.is_adjusting = False
                state.previous_width, state.previous_height = width, height
                return

            client_size, outer_size = get_client_and_outer_size(
                window,
                fallback_size=(width, height),
            )
            frame_size = calculate_logical_frame_size(
                outer_size=(width, height),
                native_outer_size=outer_size,
                native_client_size=client_size,
            )

            next_width, next_height = calculate_aspect_size(
                width=width,
                height=height,
                previous_width=state.previous_width,
                previous_height=state.previous_height,
                ratio=ratio,
                min_size=min_size,
                frame_size=frame_size,
            )

            if (next_width, next_height) == (width, height):
                state.previous_width, state.previous_height = width, height
                return

            state.is_adjusting = expect_resize_event
            state.previous_width = next_width
            state.previous_height = next_height

        window.resize(next_width, next_height)

    def handle_resized(width: int, height: int) -> None:
        correct_size(width, height, adjusting_event=True)

    def handle_shown() -> None:
        width, height = calculate_outer_size_from_native(window, fallback_size=min_size)
        correct_size(width, height, expect_resize_event=False)

    window.events.resized += handle_resized
    window.events.shown += handle_shown
