from __future__ import annotations

import ctypes
import platform
import re
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable

from src.workers.wechat_window_activation import activate_wechat_window_for_uia


WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001


Clicker = Callable[..., dict[str, Any]]
BeforeClickHook = Callable[["ArticleClickTarget"], None]


@dataclass(frozen=True)
class ArticleClickTarget:
    """主页文章标题控件的点击目标，rect 使用屏幕坐标。"""

    title: str
    rect: tuple[int, int, int, int]
    hwnd: int
    control: Any | None = None

    @property
    def click_point(self) -> tuple[int, int]:
        left, top, right, bottom = self.rect
        return ((left + right) // 2, (top + bottom) // 2)


def trigger_home_article_open(
    config: dict | None,
    article_index: int,
    *,
    home_window: Any | None = None,
    clicker: Clicker | None = None,
    before_click: BeforeClickHook | None = None,
) -> dict[str, Any]:
    """打开主页中指定序号文章；只触发一次点击，后续请求捕获交给常驻 MITM。"""
    config = config or {}
    try:
        safe_index = max(1, int(article_index))
    except (TypeError, ValueError):
        safe_index = 1

    window = home_window or find_wechat_home_window()
    if window is None:
        return {"ok": False, "reason": "wechat_home_window_not_found", "article_index": safe_index}

    activate_wechat_window_for_uia(
        window,
        delay_seconds=float(config.get("wechat_home_activate_delay_seconds", 0.5) or 0.0),
    )

    targets = collect_article_click_targets(
        window,
        max_depth=int(config.get("homepage_max_depth", 12)),
        max_nodes=int(config.get("homepage_max_nodes", 5000)),
    )
    if not targets:
        fallback_target = build_coordinate_fallback_target(window, safe_index)
        if fallback_target is None or not bool(config.get("wechat_home_coordinate_fallback_enabled", True)):
            return {"ok": False, "reason": "article_click_target_not_found", "article_index": safe_index}
        targets = [fallback_target]
    if safe_index > len(targets):
        return {
            "ok": False,
            "reason": "article_index_out_of_range",
            "article_index": safe_index,
            "visible_count": len(targets),
            "visible_targets": serialize_article_click_targets(targets),
        }

    target = targets[safe_index - 1]
    x, y = target.click_point
    try:
        if callable(before_click):
            before_click(target)
        click_count = max(1, int(config.get("article_click_count", 1)))
        pause_seconds = float(config.get("article_click_pause_seconds", 0.25))
        if clicker is not None:
            click_result = clicker(
                target.hwnd,
                x,
                y,
                click_count=click_count,
                pause_seconds=pause_seconds,
            )
        else:
            click_result = click_article_target(target, click_count=click_count, pause_seconds=pause_seconds)
    except Exception as exc:
        return {
            "ok": False,
            "reason": "article_click_failed",
            "article_index": safe_index,
            "target_title": target.title,
            "target_rect": list(target.rect),
            "click_point": [x, y],
            "visible_targets": serialize_article_click_targets(targets),
            "error": str(exc),
        }
    return {
        "ok": True,
        "article_index": safe_index,
        "target_title": target.title,
        "target_rect": list(target.rect),
        "click_point": [x, y],
        "visible_targets": serialize_article_click_targets(targets),
        "click_result": click_result,
    }


def serialize_article_click_targets(targets: list[ArticleClickTarget], *, limit: int = 12) -> list[dict[str, Any]]:
    """把本次 UIA 实际识别到的文章候选写入日志，便于页面刷新后核对点击目标。"""
    items: list[dict[str, Any]] = []
    for index, target in enumerate(targets[: max(1, int(limit))], 1):
        items.append(
            {
                "index": index,
                "title": str(target.title or "").strip(),
                "rect": list(target.rect),
                "hwnd": int(target.hwnd or 0),
            }
        )
    return items


def collect_article_click_targets(
    home_window: Any,
    *,
    max_depth: int = 12,
    max_nodes: int = 5000,
    control_from_handle: Callable[[int], Any] | None = None,
    child_hwnds_provider: Callable[[int], list[int]] | None = None,
) -> list[ArticleClickTarget]:
    """从 UIA 控件树中提取可点击文章标题；过滤导航、日期和阅读量等非标题文本。"""
    if home_window is None:
        return []

    home_hwnd = _safe_int(_safe_get(home_window, "NativeWindowHandle", 0))
    targets = _collect_article_click_targets_from_tree(
        home_window,
        home_hwnd=home_hwnd,
        max_depth=max_depth,
        max_nodes=max_nodes,
    )
    if targets:
        return targets

    get_child_hwnds = child_hwnds_provider or _enumerate_child_window_handles
    get_control = control_from_handle or _control_from_handle
    for child_hwnd in get_child_hwnds(home_hwnd):
        if child_hwnd == home_hwnd:
            continue
        child_control = _safe_call(get_control, child_hwnd)
        if child_control is None:
            continue
        targets = _collect_article_click_targets_from_tree(
            child_control,
            home_hwnd=child_hwnd,
            max_depth=max_depth,
            max_nodes=max_nodes,
        )
        if targets:
            return targets

    return []


def _collect_article_click_targets_from_tree(
    home_window: Any,
    *,
    home_hwnd: int,
    max_depth: int,
    max_nodes: int,
) -> list[ArticleClickTarget]:
    queue: deque[tuple[Any, int]] = deque([(home_window, 0)])
    targets: list[ArticleClickTarget] = []
    text_nodes: list[tuple[str, tuple[int, int, int, int]]] = []
    seen: set[tuple[str, tuple[int, int, int, int]]] = set()
    visited = 0

    while queue and visited < max_nodes:
        control, depth = queue.popleft()
        visited += 1

        if depth > 0:
            title = _control_text(control)
            rect = rect_to_tuple(_safe_get(control, "BoundingRectangle", None))
            if title and _valid_rect(rect):
                text_nodes.append((title, rect))
            if _looks_like_article_title(title) and _valid_rect(rect):
                key = (_normalize_title(title), rect)
                if key not in seen:
                    seen.add(key)
                    targets.append(
                        ArticleClickTarget(
                            title=title.strip(),
                            rect=rect,
                            hwnd=_safe_int(_safe_get(control, "NativeWindowHandle", 0)) or home_hwnd,
                            control=control,
                        )
                    )

        if depth >= max_depth:
            continue
        children = _safe_call(control.GetChildren)
        if not children:
            continue
        for child in children:
            queue.append((child, depth + 1))

    return _prefer_regular_article_list_targets(targets, text_nodes)


def click_article_target(
    target: ArticleClickTarget,
    *,
    click_count: int = 1,
    pause_seconds: float = 0.25,
) -> dict[str, Any]:
    """优先使用 Win32 消息点击；失败后再回退到 UIA 控件点击。"""
    control = target.control
    x, y = target.click_point
    try:
        return post_message_click(
            target.hwnd,
            x,
            y,
            click_count=click_count,
            pause_seconds=pause_seconds,
        )
    except Exception as exc:
        if control is None or not callable(getattr(control, "Click", None)):
            raise

        for click_index in range(max(1, int(click_count))):
            control.Click(simulateMove=False, waitTime=max(0.0, float(pause_seconds)))
            if click_index + 1 < max(1, int(click_count)):
                time.sleep(0.08)
        return {
            "method": "uia_control_click",
            "target_hwnd": int(target.hwnd),
            "screen_point": [x, y],
            "click_count": max(1, int(click_count)),
            "fallback_from": str(exc),
        }


def build_coordinate_fallback_target(home_window: Any, article_index: int) -> ArticleClickTarget | None:
    """UIA 读不到文章标题时，用主页可见列表区域做一次受控点击兜底。

    该兜底只用于打开当前可见的第 N 篇文章，不刷新页面、不重复点击；真实是否成功仍交给 MITM 捕获结果判断。
    """
    try:
        safe_index = max(1, int(article_index))
    except (TypeError, ValueError):
        safe_index = 1
    if safe_index != 1:
        return None

    hwnd = _safe_int(_safe_get(home_window, "NativeWindowHandle", 0))
    rect = rect_to_tuple(_safe_get(home_window, "BoundingRectangle", None))
    if hwnd <= 0 or not _valid_rect(rect):
        return None

    left, top, right, bottom = rect
    width = right - left
    height = bottom - top

    # 微信公众号主页首篇文章通常位于资料头部下方的文章列表左侧区域。
    x = left + int(width * 0.46)
    y = top + int(height * 0.46)
    target_rect = (max(left, x - 120), max(top, y - 24), min(right, x + 120), min(bottom, y + 24))
    return ArticleClickTarget(title="", rect=target_rect, hwnd=hwnd, control=None)


def find_wechat_home_window(auto_module: Any | None = None) -> Any | None:
    """查找已打开的微信公众号主页窗口；找不到时返回 None，由上层决定是否继续等待 MITM。"""
    if platform.system() != "Windows":
        return None
    if auto_module is None:
        try:
            import uiautomation as auto_module  # type: ignore
        except Exception:
            return None

    root = _safe_call(auto_module.GetRootControl)
    if root is None:
        return None

    candidates: list[tuple[int, Any]] = []
    for window in _safe_call(root.GetChildren) or []:
        name = str(_safe_get(window, "Name", "") or "")
        class_name = str(_safe_get(window, "ClassName", "") or "")
        process_name = _process_name(_safe_int(_safe_get(window, "ProcessId", 0)))
        if _looks_like_wechat_window(name, class_name, process_name):
            candidates.append((_home_window_score(window, name, class_name, process_name), window))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]
    return None


def _home_window_score(window: Any, name: str, class_name: str, process_name: str) -> int:
    """优先选择能读到文章候选的窗口，避免把图片/详情页误当成公众号主页。"""
    score = 0
    try:
        score += min(5, len(collect_article_click_targets(window, max_depth=8, max_nodes=1200))) * 1000
    except Exception:
        pass

    title = str(name or "").strip()
    process_text = str(process_name or "").lower()
    class_text = str(class_name or "").lower()
    if process_text in {"weixin.exe", "wechat.exe"}:
        score += 100
    if title == "微信":
        score += 50
    if title == "公众号":
        score += 20
    if process_text == "wechatappex.exe":
        score -= 30
    if "chrome_widgetwin" in class_text:
        score += 5
    return score


def post_message_click(
    hwnd: int,
    x: int,
    y: int,
    *,
    click_count: int = 1,
    pause_seconds: float = 0.25,
) -> dict[str, Any]:
    """用 Win32 消息点击窗口内坐标；不移动系统鼠标，避免打断用户当前操作。"""
    if platform.system() != "Windows":
        raise RuntimeError("post_message 点击仅支持 Windows。")
    if hwnd <= 0:
        raise RuntimeError("post_message 点击失败：目标 hwnd 为空。")

    user32 = ctypes.windll.user32
    parent_hwnd = int(hwnd)
    target_hwnd = _find_child_hwnd_containing_point(parent_hwnd, int(x), int(y)) or parent_hwnd
    point = POINT(int(x), int(y))
    if not user32.ScreenToClient(int(target_hwnd), ctypes.byref(point)):
        raise RuntimeError("post_message 点击失败：屏幕坐标转换失败。")

    lparam = _make_lparam(point.x, point.y)
    for click_index in range(max(1, int(click_count))):
        user32.PostMessageW(int(target_hwnd), WM_MOUSEMOVE, 0, lparam)
        time.sleep(0.02)
        user32.PostMessageW(int(target_hwnd), WM_LBUTTONDOWN, MK_LBUTTON, lparam)
        time.sleep(0.04)
        user32.PostMessageW(int(target_hwnd), WM_LBUTTONUP, 0, lparam)
        if click_index + 1 < max(1, int(click_count)):
            time.sleep(0.08)
    if pause_seconds > 0:
        time.sleep(pause_seconds)

    return {
        "method": "post_message",
        "parent_hwnd": parent_hwnd,
        "target_hwnd": int(target_hwnd),
        "screen_point": [int(x), int(y)],
        "client_point": [int(point.x), int(point.y)],
        "click_count": max(1, int(click_count)),
    }


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


def _control_text(control: Any) -> str:
    for attr_name in ("Name", "Value"):
        value = str(_safe_get(control, attr_name, "") or "").strip()
        if value:
            return value
    return ""


def _looks_like_article_title(text: str) -> bool:
    value = normalize_candidate_text(text)
    if not (2 <= len(value) <= 80):
        return False
    if value in {
        "公众号",
        "系统",
        "最小化",
        "最大化",
        "还原",
        "关闭",
        "文章",
        "全部",
        "贴图",
        "视频",
        "视频号",
        "今天",
        "昨天",
        "展开",
        "置顶",
        "发消息",
        "已关注",
    }:
        return False
    if re.search(r"^(?:\d{4}年)?\d{1,2}月\d{1,2}日", value):
        return False
    if re.search(r"^阅读\s*[\d.]+(?:万)?\+?\s*赞\s*\d+", value):
        return False
    if re.fullmatch(r"[\d.]+(?:万)?\+?", value):
        return False
    if re.search(r"\d+\s*篇原创", value):
        return False
    if re.search(r"\d+\s*个朋友关注", value):
        return False
    if value.startswith("视频号"):
        return False
    if _looks_like_profile_name(value):
        return False
    if _looks_like_profile_description(value):
        return False
    return True


def normalize_candidate_text(text: str) -> str:
    value = str(text or "").replace("\u200b", "").strip()
    value = re.sub(r"[\u2000-\u200a\u202f\u205f\u3000]+", " ", value)
    return re.sub(r"\s+", " ", value)


def _prefer_regular_article_list_targets(
    targets: list[ArticleClickTarget],
    text_nodes: list[tuple[str, tuple[int, int, int, int]]],
) -> list[ArticleClickTarget]:
    """优先选择“日期 + 标题 + 阅读赞”的普通文章列表，跳过置顶专题/封面文案。"""
    regular_targets = [
        target
        for target in targets
        if _has_date_anchor_above(target.rect, text_nodes) and _has_metric_anchor_below(target.rect, text_nodes)
    ]
    return regular_targets or targets


def _has_date_anchor_above(
    rect: tuple[int, int, int, int],
    text_nodes: list[tuple[str, tuple[int, int, int, int]]],
) -> bool:
    left, top, right, _bottom = rect
    for text, node_rect in text_nodes:
        node_text = normalize_candidate_text(text)
        node_left, node_top, node_right, node_bottom = node_rect
        if not _is_article_date_anchor(node_text):
            continue
        if not (0 <= top - node_bottom <= 160):
            continue
        if abs(node_left - left) <= 80 or _rects_overlap_horizontally((left, top, right, top), node_rect):
            return True
    return False


def _has_metric_anchor_below(
    rect: tuple[int, int, int, int],
    text_nodes: list[tuple[str, tuple[int, int, int, int]]],
) -> bool:
    left, _top, right, bottom = rect
    for text, node_rect in text_nodes:
        node_text = normalize_candidate_text(text)
        node_left, node_top, node_right, _node_bottom = node_rect
        if not _is_article_metric_anchor(node_text):
            continue
        if not (0 <= node_top - bottom <= 120):
            continue
        if abs(node_left - left) <= 80 or _rects_overlap_horizontally((left, bottom, right, bottom), node_rect):
            return True
    return False


def _is_article_date_anchor(value: str) -> bool:
    return value in {"今天", "昨天"} or bool(re.search(r"^(?:\d{4}年)?\d{1,2}月\d{1,2}日$", value))


def _is_article_metric_anchor(value: str) -> bool:
    return bool(re.search(r"阅读\s*[\d.]+(?:万)?\+?.*赞\s*\d+", value))


def _rects_overlap_horizontally(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> bool:
    return min(first[2], second[2]) > max(first[0], second[0])


def _looks_like_profile_name(value: str) -> bool:
    if len(value) > 5:
        return False
    if re.search(r"[，。！？、；：“”‘’《》（）()\[\]【】,.!?;:]", value):
        return False
    return bool(re.search(r"[\u4e00-\u9fff]", value))


def _looks_like_profile_description(value: str) -> bool:
    # 公众号简介常包含“官方账号/订阅号”等身份词，不能作为文章标题点击。
    if any(
        marker in value
        for marker in (
            "官方账号",
            "官方公众号",
            "官方微信",
            "订阅号",
            "服务号",
            "资讯号",
        )
    ) and re.search(r"[。，、；;！!？?]", value):
        return True
    if len(value) > 18:
        return False
    if "、" not in value or not value.endswith("。"):
        return False
    if re.search(r"[\d“”《》【】]", value):
        return False
    return True


def _valid_rect(rect: tuple[int, int, int, int]) -> bool:
    left, top, right, bottom = rect
    return right > left and bottom > top and (right - left) >= 20 and (bottom - top) >= 10


def _normalize_title(text: str) -> str:
    return "".join(str(text or "").split())


def _make_lparam(x: int, y: int) -> int:
    return (int(y) & 0xFFFF) << 16 | (int(x) & 0xFFFF)


def _find_child_hwnd_containing_point(parent_hwnd: int, x: int, y: int) -> int:
    """选中包含点击坐标的最小可见子窗口，把点击消息投递给真实内容区。"""
    if platform.system() != "Windows" or parent_hwnd <= 0:
        return 0

    user32 = ctypes.windll.user32
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


def _enumerate_child_window_handles(parent_hwnd: int) -> list[int]:
    """枚举微信内嵌浏览器子窗口；顶层 UIA 只暴露外壳时，用它兜底读取正文控件。"""
    if platform.system() != "Windows" or parent_hwnd <= 0:
        return []

    user32 = ctypes.windll.user32
    child_hwnds: list[int] = []
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def callback(hwnd, _lparam):
        child_hwnds.append(int(hwnd))
        return True

    user32.EnumChildWindows(int(parent_hwnd), enum_proc(callback), 0)
    return child_hwnds


def _control_from_handle(hwnd: int):
    try:
        import uiautomation as auto

        return auto.ControlFromHandle(hwnd)
    except Exception:
        return None


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


def _process_name(process_id: int) -> str:
    if process_id <= 0:
        return ""
    try:
        import psutil

        return str(psutil.Process(process_id).name() or "")
    except Exception:
        return ""


def _looks_like_wechat_window(name: str, class_name: str, process_name: str) -> bool:
    title = str(name or "").strip()
    lower_title = title.lower()
    class_text = str(class_name or "").lower()
    process_text = str(process_name or "").lower()

    if "access wechat article" in lower_title or "visual studio code" in lower_title:
        return False
    if title == "公众号" or "微信公众号" in title:
        return True
    if process_text in {"wechat.exe", "wechatappex.exe", "weixin.exe"}:
        return title == "微信" or "公众号" in title or "chrome_widgetwin" in class_text
    return "微信" in title and "公众号" in title
