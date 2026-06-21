from __future__ import annotations


Size = tuple[int, int]


def get_client_and_outer_size(window, fallback_size: Size) -> tuple[Size, Size]:
    """读取 pywebview 原生窗口的内容区和外框尺寸，读取失败时使用兜底尺寸。"""
    native_window = getattr(window, "native", None)
    if not native_window:
        return fallback_size, fallback_size

    client_size = getattr(native_window, "ClientSize", None)
    outer_size = getattr(native_window, "Size", None)
    if not client_size or not outer_size:
        return fallback_size, fallback_size

    client = (int(client_size.Width), int(client_size.Height))
    outer = (int(outer_size.Width), int(outer_size.Height))

    return client, outer


def calculate_outer_size_for_content(
    outer_size: Size,
    client_size: Size,
    content_height: int,
    min_size: Size,
) -> Size:
    """根据网页内容高度，计算需要设置到原生窗口外框上的尺寸。"""
    target_width, min_height = min_size
    _outer_width, outer_height = outer_size
    _client_width, client_height = client_size

    frame_height = max(0, outer_height - client_height)
    next_height = max(min_height, int(round(content_height)) + frame_height)

    # 当前需求是“打开后窗口宽度固定 1200，页面按此宽度缩放”，因此高度自适应时也要把外框宽度压回配置宽度。
    return target_width, next_height
