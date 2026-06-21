from __future__ import annotations

import ctypes
import platform
import time
from typing import Any


SW_RESTORE = 9


def activate_wechat_window_for_uia(
    window: Any,
    *,
    delay_seconds: float = 0.5,
) -> dict[str, Any]:
    """软激活微信主页窗口，促使微信内置浏览器刷新 UIA 控件树。

    这里只恢复窗口、置前并尝试设置焦点，不刷新页面、不点击文章链接，因此不会重复请求带 key 的文章 URL。
    """
    hwnd = _safe_int(_safe_get(window, "NativeWindowHandle", 0))
    if platform.system() != "Windows":
        return {"ok": False, "reason": "not_windows", "hwnd": hwnd}
    if hwnd <= 0:
        _sleep(delay_seconds)
        return {"ok": False, "reason": "missing_hwnd", "hwnd": hwnd}

    result: dict[str, Any] = {"ok": True, "reason": "activated", "hwnd": hwnd}
    try:
        user32 = ctypes.windll.user32
        user32.ShowWindow(int(hwnd), SW_RESTORE)
        result["showWindow"] = True
        result["setForegroundWindow"] = bool(user32.SetForegroundWindow(int(hwnd)))
    except Exception as exc:
        result["ok"] = False
        result["reason"] = "win32_activate_failed"
        result["error"] = str(exc)

    focus_result = _try_set_uia_focus(window)
    result["setFocus"] = focus_result.get("ok")
    if focus_result.get("error"):
        result["focusError"] = focus_result.get("error")

    _sleep(delay_seconds)
    return result


def _try_set_uia_focus(window: Any) -> dict[str, Any]:
    set_focus = getattr(window, "SetFocus", None)
    if not callable(set_focus):
        return {"ok": False, "reason": "focus_not_supported"}
    try:
        set_focus()
        return {"ok": True, "reason": "focused"}
    except Exception as exc:
        return {"ok": False, "reason": "focus_failed", "error": str(exc)}


def _sleep(delay_seconds: float) -> None:
    delay = max(0.0, float(delay_seconds or 0.0))
    if delay > 0:
        time.sleep(delay)


def _safe_get(obj: Any, attr_name: str, default: Any = "") -> Any:
    try:
        return getattr(obj, attr_name)
    except Exception:
        return default


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0
