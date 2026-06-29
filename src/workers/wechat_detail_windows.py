from __future__ import annotations

import ctypes
import platform
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any


WM_CLOSE = 0x0010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
EXPLICIT_HOME_WINDOW_TITLES = {"公众号", "服务号", "订阅号"}
WECHAT_BROWSER_CLASS_PREFIX = "Chrome_WidgetWin_"
WECHAT_BROWSER_PROCESS_NAMES = {"wechatappex.exe", "weixin.exe", "wechat.exe"}


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


def close_wechat_article_detail_windows(
    *,
    homepage_hwnd: int = 0,
    pause_seconds: float = 0.15,
    min_width: int = 300,
    min_height: int = 300,
    reason: str = "",
) -> dict[str, Any]:
    """关闭微信内置浏览器详情窗口，保留当前公众号主页窗口。"""
    result: dict[str, Any] = {
        "ok": True,
        "closed": [],
        "skipped": [],
        "errors": [],
        "reason": str(reason or ""),
    }
    if platform.system() != "Windows":
        result["ok"] = False
        result["errors"].append({"reason": "unsupported_platform"})
        return result

    user32 = ctypes.windll.user32
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def callback(hwnd_value: int, _lparam: int) -> bool:
        hwnd = int(hwnd_value)
        if not _is_target_detail_window(
            hwnd,
            homepage_hwnd=homepage_hwnd,
            min_width=min_width,
            min_height=min_height,
        ):
            return True

        window_info = _build_window_info(hwnd)
        try:
            if not user32.PostMessageW(hwnd, WM_CLOSE, 0, 0):
                raise RuntimeError("PostMessageW(WM_CLOSE) 返回失败")
            result["closed"].append(window_info)
            if pause_seconds > 0:
                time.sleep(pause_seconds)
        except Exception as exc:
            window_info["error"] = str(exc)
            result["errors"].append(window_info)
        return True

    try:
        user32.EnumWindows(enum_proc(callback), 0)
    except Exception as exc:
        result["ok"] = False
        result["errors"].append({"reason": "enum_windows_failed", "error": str(exc)})
    if result["errors"]:
        result["ok"] = False
    return result


def _is_target_detail_window(
    hwnd: int,
    *,
    homepage_hwnd: int,
    min_width: int,
    min_height: int,
) -> bool:
    user32 = ctypes.windll.user32
    if hwnd <= 0 or hwnd == int(homepage_hwnd or 0):
        return False
    if not bool(user32.IsWindowVisible(hwnd)):
        return False
    if not _is_wechat_browser_class(_get_window_class(hwnd)):
        return False
    if _get_window_text(hwnd).strip() in EXPLICIT_HOME_WINDOW_TITLES:
        return False

    rect = _get_window_rect(hwnd)
    width = rect[2] - rect[0]
    height = rect[3] - rect[1]
    if width < min_width or height < min_height:
        return False

    return _is_wechat_browser_process(_get_window_process_name(hwnd))


def _is_wechat_browser_class(class_name: str) -> bool:
    """微信内置浏览器由 Chromium 窗口承载，不同版本后缀可能不同。"""
    return str(class_name or "").startswith(WECHAT_BROWSER_CLASS_PREFIX)


def _is_wechat_browser_process(process_name: str) -> bool:
    return Path(str(process_name or "")).name.lower() in WECHAT_BROWSER_PROCESS_NAMES


def _build_window_info(hwnd: int) -> dict[str, Any]:
    return {
        "hwnd": int(hwnd),
        "title": _get_window_text(hwnd),
        "className": _get_window_class(hwnd),
        "processName": _get_window_process_name(hwnd),
        "rect": list(_get_window_rect(hwnd)),
    }


def _get_window_text(hwnd: int) -> str:
    user32 = ctypes.windll.user32
    length = int(user32.GetWindowTextLengthW(hwnd) or 0)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def _get_window_class(hwnd: int) -> str:
    user32 = ctypes.windll.user32
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def _get_window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)


def _get_window_process_name(hwnd: int) -> str:
    user32 = ctypes.windll.user32
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if int(pid.value or 0) <= 0:
        return ""

    name_from_query = _query_process_image_name(int(pid.value))
    if name_from_query:
        return Path(name_from_query).name

    try:
        import psutil  # type: ignore

        return str(psutil.Process(int(pid.value)).name() or "")
    except Exception:
        return ""


def _query_process_image_name(pid: int) -> str:
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return ""
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buffer))
            query = getattr(kernel32, "QueryFullProcessImageNameW", None)
            if query is None:
                return ""
            if not query(handle, 0, buffer, ctypes.byref(size)):
                return ""
            return buffer.value
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return ""
