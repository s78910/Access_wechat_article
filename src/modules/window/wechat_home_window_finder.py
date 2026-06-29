from __future__ import annotations

import platform
from typing import Any, Callable


EXPLICIT_HOME_WINDOW_TITLES = {"公众号", "服务号", "订阅号"}
GENERIC_WECHAT_WINDOW_TITLES = {"微信", "Weixin", "WeChat"}

TargetCollector = Callable[..., list[Any]]


def find_wechat_home_window(
    auto_module: Any | None = None,
    *,
    target_collector: TargetCollector | None = None,
) -> Any | None:
    """查找真实公众号/服务号主页窗口；聊天主窗口不作为主页候选。"""
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
        if not is_wechat_home_window_candidate(name, class_name, process_name):
            continue
        candidates.append(
            (
                score_wechat_home_window(
                    window,
                    name,
                    class_name,
                    process_name,
                    target_collector=target_collector,
                ),
                window,
            )
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def is_wechat_home_window_candidate(name: str, class_name: str, process_name: str = "") -> bool:
    """只接受公众号/服务号主页类窗口，避免微信聊天主窗口被误识别。"""
    title = str(name or "").strip()
    lower_title = title.lower()

    if "access wechat article" in lower_title or "access_wechat_article" in lower_title:
        return False
    if "visual studio code" in lower_title:
        return False
    if title in EXPLICIT_HOME_WINDOW_TITLES:
        return True
    return "微信公众号" in title


def score_wechat_home_window(
    window: Any,
    name: str,
    class_name: str,
    process_name: str,
    *,
    target_collector: TargetCollector | None = None,
) -> int:
    """按主页可信度排序；窗口身份优先，文章候选数量只作同类窗口内的加分。"""
    score = 0
    title = str(name or "").strip()
    process_text = str(process_name or "").lower()
    class_text = str(class_name or "").lower()
    window_rect = rect_to_tuple(_safe_get(window, "BoundingRectangle", None))

    if title in EXPLICIT_HOME_WINDOW_TITLES:
        score += 10000
    if process_text == "wechatappex.exe":
        score += 2000
    if "chrome_widgetwin" in class_text:
        score += 1000
    if not _valid_rect(window_rect):
        score -= 10000

    target_count = _collect_target_count(window, target_collector=target_collector)
    score += min(5, target_count) * 100
    return score


def rect_to_tuple(rect: Any) -> tuple[int, int, int, int]:
    if isinstance(rect, (list, tuple)) and len(rect) == 4:
        return tuple(int(item) for item in rect)
    for names in (("left", "top", "right", "bottom"), ("Left", "Top", "Right", "Bottom")):
        values = [_safe_get(rect, name, None) for name in names]
        if all(value is not None for value in values):
            return tuple(int(value) for value in values)
    return (0, 0, 0, 0)


def _collect_target_count(window: Any, *, target_collector: TargetCollector | None = None) -> int:
    collector = target_collector
    if collector is None:
        try:
            from src.workers.home_article_clicker import collect_article_click_targets

            collector = collect_article_click_targets
        except Exception:
            return 0
    try:
        return len(collector(window, max_depth=8, max_nodes=1200))
    except Exception:
        return 0


def _valid_rect(rect: tuple[int, int, int, int]) -> bool:
    left, top, right, bottom = rect
    return right > left and bottom > top


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


def _safe_call(func, *args):
    try:
        return func(*args)
    except Exception:
        return None


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


__all__ = [
    "EXPLICIT_HOME_WINDOW_TITLES",
    "GENERIC_WECHAT_WINDOW_TITLES",
    "find_wechat_home_window",
    "is_wechat_home_window_candidate",
    "score_wechat_home_window",
]
