from __future__ import annotations

import ctypes
import platform
import re
import time
from collections import deque
from typing import Any, Callable


VK_CONTROL = 0x11
VK_F5 = 0x74
KEYEVENTF_KEYUP = 0x0002
SW_RESTORE = 9

ProcessNameResolver = Callable[[int], str]
KeySender = Callable[[int], None]


def find_visible_wechat_article_window(
    expected_title: str,
    *,
    auto_module: Any | None = None,
    process_name_resolver: ProcessNameResolver | None = None,
    max_depth: int = 8,
    max_nodes: int = 2000,
) -> dict[str, Any] | None:
    """从微信内置浏览器窗口中寻找已打开的目标文章页。"""
    if auto_module is None:
        if platform.system() != "Windows":
            return None
        try:
            import uiautomation as auto_module  # type: ignore
        except Exception:
            return None

    resolver = process_name_resolver or _process_name
    root = _safe_call(auto_module.GetRootControl)
    if root is None:
        return None

    for window in _safe_call(root.GetChildren) or []:
        hwnd = _safe_int(_safe_get(window, "NativeWindowHandle", 0))
        process_name = resolver(_safe_int(_safe_get(window, "ProcessId", 0)))
        if hwnd <= 0 or not _looks_like_wechat_article_host(window, process_name):
            continue

        document_title = _find_matching_document_title(
            window,
            expected_title,
            max_depth=max_depth,
            max_nodes=max_nodes,
        )
        if document_title:
            return {
                "hwnd": hwnd,
                "window_title": str(_safe_get(window, "Name", "") or ""),
                "document_title": document_title,
                "process_name": process_name,
                "reload_button": _find_reload_button(window, max_depth=max_depth, max_nodes=max_nodes),
            }

    return None


def refresh_visible_wechat_article_window(
    expected_title: str,
    *,
    auto_module: Any | None = None,
    process_name_resolver: ProcessNameResolver | None = None,
    key_sender: KeySender | None = None,
) -> dict[str, Any]:
    """对已打开的目标文章窗口发送一次 Ctrl+F5，尽量绕过微信内置浏览器缓存。"""
    if platform.system() != "Windows" and auto_module is None:
        return {"ok": False, "reason": "unsupported_platform"}

    found = find_visible_wechat_article_window(
        expected_title,
        auto_module=auto_module,
        process_name_resolver=process_name_resolver,
    )
    if not found:
        return {"ok": False, "reason": "article_window_not_found", "expected_title": expected_title}

    try:
        sender = key_sender or send_ctrl_f5_to_window
        sender(int(found["hwnd"]))
        method = "ctrl_f5"
    except Exception as exc:
        reload_button = found.get("reload_button")
        if reload_button is None:
            public_found = {key: value for key, value in found.items() if key != "reload_button"}
            return {
                "ok": False,
                "reason": "refresh_failed",
                "expected_title": expected_title,
                "error": str(exc),
                **public_found,
            }
        try:
            _click_reload_button(reload_button)
            method = "reload_button_after_ctrl_f5_failed"
        except Exception as reload_exc:
            public_found = {key: value for key, value in found.items() if key != "reload_button"}
            return {
                "ok": False,
                "reason": "refresh_failed",
                "expected_title": expected_title,
                "error": f"{exc}; reload_button={reload_exc}",
                **public_found,
            }

    public_found = {key: value for key, value in found.items() if key != "reload_button"}
    return {"ok": True, "reason": "refreshed", "method": method, "expected_title": expected_title, **public_found}


def send_ctrl_f5_to_window(hwnd: int) -> None:
    """把目标窗口置前后发送 Ctrl+F5；不修改系统代理和 MITM 状态。"""
    if platform.system() != "Windows":
        raise RuntimeError("刷新微信文章窗口仅支持 Windows。")
    if hwnd <= 0:
        raise RuntimeError("刷新微信文章窗口失败：窗口句柄为空。")

    user32 = ctypes.windll.user32
    user32.ShowWindow(int(hwnd), SW_RESTORE)
    user32.SetForegroundWindow(int(hwnd))
    time.sleep(0.15)
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_F5, 0, 0, 0)
    user32.keybd_event(VK_F5, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def _find_matching_document_title(
    root: Any,
    expected_title: str,
    *,
    max_depth: int,
    max_nodes: int,
) -> str:
    expected = _normalize_title(expected_title)
    if not expected:
        return ""

    queue: deque[tuple[Any, int]] = deque([(root, 0)])
    visited = 0
    fallback_title = ""
    while queue and visited < max_nodes:
        control, depth = queue.popleft()
        visited += 1

        name = str(_safe_get(control, "Name", "") or "").strip()
        control_type = str(_safe_get(control, "ControlTypeName", "") or "")
        if name and _titles_match(name, expected_title):
            if control_type == "DocumentControl":
                return name
            fallback_title = fallback_title or name

        if depth >= max_depth:
            continue
        for child in _safe_call(control.GetChildren) or []:
            queue.append((child, depth + 1))

    return fallback_title


def _find_reload_button(root: Any, *, max_depth: int, max_nodes: int) -> Any | None:
    queue: deque[tuple[Any, int]] = deque([(root, 0)])
    visited = 0
    while queue and visited < max_nodes:
        control, depth = queue.popleft()
        visited += 1

        name = str(_safe_get(control, "Name", "") or "").strip()
        control_type = str(_safe_get(control, "ControlTypeName", "") or "")
        if control_type == "ButtonControl" and name == "重新加载" and callable(getattr(control, "Click", None)):
            return control

        if depth >= max_depth:
            continue
        for child in _safe_call(control.GetChildren) or []:
            queue.append((child, depth + 1))
    return None


def _click_reload_button(control: Any) -> None:
    control.Click(simulateMove=False, waitTime=0.1)


def _titles_match(actual: str, expected: str) -> bool:
    actual_norm = _normalize_title(actual)
    expected_norm = _normalize_title(expected)
    if not actual_norm or not expected_norm:
        return False
    return actual_norm in expected_norm or expected_norm in actual_norm


def _normalize_title(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").replace("\u200b", "")).strip()


def _looks_like_wechat_article_host(window: Any, process_name: str) -> bool:
    title = str(_safe_get(window, "Name", "") or "").strip()
    class_name = str(_safe_get(window, "ClassName", "") or "").lower()
    process_text = str(process_name or "").lower()
    if title == "公众号":
        return False
    if process_text in {"wechat.exe", "wechatappex.exe", "weixin.exe"}:
        return title == "微信" or "chrome_widgetwin" in class_name
    # 当前项目不强制安装 psutil；进程名不可读时，用微信文章窗口的稳定标题和类名兜底。
    return title == "微信" and "chrome_widgetwin" in class_name


def _process_name(process_id: int) -> str:
    if process_id <= 0:
        return ""
    try:
        import psutil

        return str(psutil.Process(process_id).name() or "")
    except Exception:
        return ""


def _safe_get(obj: Any, attr_name: str, default: Any = "") -> Any:
    try:
        return getattr(obj, attr_name)
    except Exception:
        return default


def _safe_call(func: Any, *args: Any) -> Any:
    try:
        return func(*args)
    except Exception:
        return None


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0
