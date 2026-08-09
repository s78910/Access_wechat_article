from __future__ import annotations

import ctypes
from dataclasses import dataclass
import platform
import time
from typing import Any, Callable

from src.domain.models import ArticleTarget


WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001


@dataclass(frozen=True, slots=True)
class ClickResult:
    method: str
    target_handle: int
    click_x: int
    click_y: int
    native_error: str = ""


class ArticleClicker:
    """对已刷新确认的文章目标执行一次窗口消息点击。"""

    def __init__(
        self,
        *,
        native_click: Callable[[int, int, int], None] | None = None,
        uia_click: Callable[[Any], None] | None = None,
        screen_click: Callable[..., None] | None = None,
        screen_click_wait_seconds: float = 0.3,
    ) -> None:
        self._native_click = native_click or _post_message_click
        # 兼容旧工厂/测试注入参数，但主页点击不再调用 UIA Click 或系统鼠标。
        del uia_click, screen_click, screen_click_wait_seconds

    def click(self, target: ArticleTarget) -> ClickResult:
        try:
            # 主页文章点击统一发给微信窗口/子窗口，不调用系统鼠标，避免抢占用户当前鼠标。
            self._native_click(
                target.home_window_handle,
                target.click_x,
                target.click_y,
            )
            return ClickResult(
                method="win32_post_message",
                target_handle=target.home_window_handle,
                click_x=target.click_x,
                click_y=target.click_y,
            )
        except Exception as native_error:
            raise RuntimeError(f"Win32 点击失败：{native_error}") from native_error


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _post_message_click(hwnd: int, screen_x: int, screen_y: int) -> None:
    if platform.system() != "Windows":
        raise OSError("Win32 点击仅支持 Windows")
    if hwnd <= 0:
        raise ValueError("点击目标 hwnd 不能为空")
    user32 = ctypes.windll.user32
    screen_point = _Point(int(screen_x), int(screen_y))
    setter, previous_context = _enter_per_monitor_dpi_context(user32)
    try:
        # UIA 给出物理坐标；WindowFromPoint 也必须在同一个 DPI 坐标域内执行。
        target_hwnd = _resolve_click_message_target(user32, int(hwnd), screen_point)
        point = _Point(screen_point.x, screen_point.y)
        if not user32.ScreenToClient(target_hwnd, ctypes.byref(point)):
            raise RuntimeError("屏幕坐标转换为窗口坐标失败")
    finally:
        _restore_dpi_context(setter, previous_context)
    lparam = (point.y & 0xFFFF) << 16 | (point.x & 0xFFFF)
    if not user32.PostMessageW(target_hwnd, WM_MOUSEMOVE, 0, lparam):
        raise RuntimeError("发送鼠标移动消息失败")
    time.sleep(0.02)
    if not user32.PostMessageW(target_hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam):
        raise RuntimeError("发送鼠标按下消息失败")
    time.sleep(0.04)
    if not user32.PostMessageW(target_hwnd, WM_LBUTTONUP, 0, lparam):
        raise RuntimeError("发送鼠标释放消息失败")
    # Chromium 会异步处理合成鼠标消息，短暂等待可避免标题轮询先于导航开始。
    time.sleep(0.25)


def _resolve_click_message_target(user32: Any, home_hwnd: int, point: _Point) -> int:
    """只允许把消息发给主页本身或鼠标点下方的主页子窗口。"""
    try:
        candidate = int(user32.WindowFromPoint(point) or 0)
        if candidate == int(home_hwnd):
            return candidate
        if candidate > 0 and bool(user32.IsChild(int(home_hwnd), candidate)):
            return candidate
    except Exception:
        pass
    return int(home_hwnd)


def _screen_to_client_physical(user32: Any, hwnd: int, point: _Point) -> None:
    """在每显示器 DPI 坐标域中转换 UIA 物理坐标，避免缩放后点击偏移。"""
    setter, previous_context = _enter_per_monitor_dpi_context(user32)
    try:
        if not user32.ScreenToClient(int(hwnd), ctypes.byref(point)):
            raise RuntimeError("屏幕坐标转换为窗口坐标失败")
    finally:
        _restore_dpi_context(setter, previous_context)


def _enter_per_monitor_dpi_context(user32: Any) -> tuple[Any, Any]:
    setter = getattr(user32, "SetThreadDpiAwarenessContext", None)
    previous_context: Any = None
    if callable(setter):
        try:
            setter.argtypes = [ctypes.c_void_p]
            setter.restype = ctypes.c_void_p
        except Exception:
            pass
        previous_context = setter(ctypes.c_void_p(-4))
    return setter, previous_context


def _restore_dpi_context(setter: Any, previous_context: Any) -> None:
    if callable(setter) and previous_context:
        raw_context = getattr(previous_context, "value", previous_context)
        setter(ctypes.c_void_p(raw_context))
