from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


NAVIGATION_TABS = {"全部", "贴图", "文章", "视频号"}
WINDOW_TITLES = {"公众号", "服务号", "订阅号", "微信", "WeChat", "Weixin"}
CONTROL_NOISE = {
    "",
    "搜索",
    "更多",
    "最小化",
    "最大化",
    "关闭",
    "...",
    "•••",
    "···",
}


def _rect_to_tuple(rect: Any) -> tuple[int, int, int, int]:
    if rect is None:
        return (0, 0, 0, 0)
    try:
        return (
            int(getattr(rect, "left", 0)),
            int(getattr(rect, "top", 0)),
            int(getattr(rect, "right", 0)),
            int(getattr(rect, "bottom", 0)),
        )
    except Exception:
        pass
    try:
        return (
            int(getattr(rect, "Left", 0)),
            int(getattr(rect, "Top", 0)),
            int(getattr(rect, "Right", 0)),
            int(getattr(rect, "Bottom", 0)),
        )
    except Exception:
        return (0, 0, 0, 0)


def _valid_rect(rect: tuple[int, int, int, int]) -> bool:
    left, top, right, bottom = rect
    return right > left and bottom > top


def _safe_attr(obj: Any, name: str, default: Any = "") -> Any:
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def _safe_call(func: Any, *args: Any, default: Any = None) -> Any:
    try:
        return func(*args)
    except Exception:
        return default


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _looks_like_account_name(text: str) -> bool:
    text = _normalize_text(text)
    if not text or text in NAVIGATION_TABS or text in WINDOW_TITLES or text in CONTROL_NOISE:
        return False
    if len(text) > 24:
        return False
    if any(mark in text for mark in ("阅读", "赞", "月", "日", "关注", "原创", "视频号")):
        return False
    return True


def _collect_uia_nodes(control: Any, *, max_depth: int = 10, max_nodes: int = 5000) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    stack: list[tuple[Any, int]] = [(control, 0)]
    while stack and len(nodes) < max_nodes:
        item, depth = stack.pop()
        name = _normalize_text(_safe_attr(item, "Name", ""))
        rect = _rect_to_tuple(_safe_attr(item, "BoundingRectangle", None))
        control_type = str(_safe_attr(item, "ControlTypeName", "") or _safe_attr(item, "ControlType", ""))
        if name or _valid_rect(rect):
            nodes.append(
                {
                    "depth": depth,
                    "name": name,
                    "controlType": control_type,
                    "rect": rect,
                }
            )
        if depth >= max_depth:
            continue
        children = _safe_call(getattr(item, "GetChildren", None), default=[]) if hasattr(item, "GetChildren") else []
        for child in reversed(list(children or [])):
            stack.append((child, depth + 1))
    return nodes


def _dedupe_lines(nodes: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for node in nodes:
        name = _normalize_text(node.get("name"))
        if not name or name in seen:
            continue
        seen.add(name)
        lines.append(name)
    return lines


def _select_account_from_top_region(
    nodes: list[dict[str, Any]],
    window_rect: tuple[int, int, int, int],
) -> dict[str, Any]:
    left, top, right, _bottom = window_rect
    nav_nodes = [
        node
        for node in nodes
        if node.get("name") in NAVIGATION_TABS and _valid_rect(tuple(node.get("rect") or (0, 0, 0, 0)))
    ]
    nav_top = min((node["rect"][1] for node in nav_nodes), default=top + 180)
    top_band_bottom = nav_top + 8
    candidates: list[dict[str, Any]] = []
    for node in nodes:
        name = _normalize_text(node.get("name"))
        rect = tuple(node.get("rect") or (0, 0, 0, 0))
        if not _valid_rect(rect):
            continue
        n_left, n_top, n_right, n_bottom = rect
        if not _looks_like_account_name(name):
            continue
        if n_top < top + 40 or n_bottom > top_band_bottom:
            continue
        if n_left < left + 20 or n_left > min(right, left + 470):
            continue
        score = 0
        score += max(0, 200 - abs(n_bottom - nav_top))
        score += max(0, 120 - abs(n_left - (left + 120)))
        score += min(80, (n_right - n_left) + (n_bottom - n_top))
        candidates.append({**node, "score": score})

    candidates.sort(key=lambda item: (-int(item["score"]), item["rect"][1], item["rect"][0]))
    return {
        "navTop": nav_top,
        "candidates": candidates[:10],
        "accountName": candidates[0]["name"] if candidates else "",
    }


def main() -> int:
    try:
        import uiautomation as auto
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"uiautomation 导入失败：{exc}"}, ensure_ascii=False, indent=2))
        return 2

    from src.modules.window.wechat_home_window_finder import find_wechat_home_window
    from src.workers.wechat_home import detect_wechat_home_window, parse_wechat_home_text

    home_window = find_wechat_home_window()
    if home_window is None:
        print(json.dumps({"ok": False, "error": "未找到公众号/服务号主页窗口"}, ensure_ascii=False, indent=2))
        return 1

    hwnd = int(_safe_attr(home_window, "NativeWindowHandle", 0) or 0)
    control = auto.ControlFromHandle(hwnd) if hwnd else home_window
    window_rect = _rect_to_tuple(_safe_attr(control, "BoundingRectangle", None))
    nodes = _collect_uia_nodes(control)
    lines = _dedupe_lines(nodes)
    parsed = parse_wechat_home_text("\n".join(lines))
    top_probe = _select_account_from_top_region(nodes, window_rect)
    existing_snapshot = detect_wechat_home_window(activate=True)
    top_nodes = [
        node
        for node in nodes
        if node.get("name")
        and _valid_rect(tuple(node.get("rect") or (0, 0, 0, 0)))
        and window_rect[1] <= node["rect"][1] <= window_rect[1] + 230
    ][:80]

    result = {
        "ok": True,
        "window": {
            "name": _normalize_text(_safe_attr(home_window, "Name", "")),
            "className": _normalize_text(_safe_attr(home_window, "ClassName", "")),
            "hwnd": hwnd,
            "rect": window_rect,
        },
        "existingDetector": existing_snapshot.to_dict(),
        "fullTextParse": parsed.to_dict(),
        "topRegionProbe": top_probe,
        "topVisibleNodes": top_nodes,
        "firstLines": lines[:80],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
