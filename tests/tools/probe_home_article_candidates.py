from __future__ import annotations

import json
import re
import sys
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.modules.window.wechat_home_window_finder import find_wechat_home_window
from src.workers.home_article_clicker import (
    collect_article_click_targets,
    normalize_candidate_text,
    rect_to_tuple,
)


CONFIG = {
    # 只读取当前窗口，不点击、不滚动，避免影响用户正在打开的微信主页。
    "max_depth": 12,
    "max_nodes": 5000,
    "target_keywords": [
        "6月11日起",
        "公益直播课上线",
        "研招调剂服务系统",
    ],
    "artifact_dir": PROJECT_ROOT / "tests" / "artifacts" / "home_candidate_probe",
}


@dataclass(frozen=True)
class TextNode:
    depth: int
    path: str
    text: str
    rect: tuple[int, int, int, int]
    control_type: str
    class_name: str
    hwnd: int


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    report = probe_current_home_article_candidates()
    artifact_dir = Path(CONFIG["artifact_dir"])
    artifact_dir.mkdir(parents=True, exist_ok=True)
    output_path = artifact_dir / f"home_article_candidates_{datetime.now():%Y%m%d_%H%M%S}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = json.dumps(build_console_summary(report, output_path), ensure_ascii=False, indent=2)
    try:
        print(summary)
    except UnicodeEncodeError:
        print(summary.encode("unicode_escape").decode("ascii"))


def probe_current_home_article_candidates() -> dict[str, Any]:
    try:
        import uiautomation as auto  # noqa: F401
    except Exception as exc:
        return {
            "ok": False,
            "reason": "uiautomation_unavailable",
            "error": str(exc),
        }

    home_window = find_wechat_home_window(target_collector=collect_article_click_targets)
    if home_window is None:
        return {"ok": False, "reason": "wechat_home_window_not_found"}

    max_depth = int(CONFIG["max_depth"])
    max_nodes = int(CONFIG["max_nodes"])
    text_nodes = collect_text_nodes(home_window, max_depth=max_depth, max_nodes=max_nodes)
    final_targets = collect_article_click_targets(home_window, max_depth=max_depth, max_nodes=max_nodes)
    raw_title_candidates = [
        node
        for node in text_nodes
        if looks_like_article_title(node.text) and valid_rect(node.rect)
    ]
    nav_bottom = detect_nav_row_bottom(text_nodes)
    markers = build_section_markers(text_nodes, nav_bottom=nav_bottom)
    target_keywords = [str(item) for item in CONFIG["target_keywords"]]

    return {
        "ok": True,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "home_window": summarize_control(home_window),
        "nav_bottom": nav_bottom,
        "section_markers": markers,
        "target_keywords": target_keywords,
        "keyword_nodes": [
            analyze_text_node(node, text_nodes, nav_bottom=nav_bottom, markers=markers, final_targets=final_targets)
            for node in text_nodes
            if any(keyword in node.text for keyword in target_keywords)
        ],
        "raw_title_candidates": [
            analyze_text_node(node, text_nodes, nav_bottom=nav_bottom, markers=markers, final_targets=final_targets)
            for node in raw_title_candidates
        ],
        "final_click_targets": [
            {
                "index": index,
                "title": str(getattr(target, "title", "") or "").strip(),
                "rect": list(rect_to_tuple(getattr(target, "rect", None))),
                "hwnd": int(getattr(target, "hwnd", 0) or 0),
                "has_metric_anchor_below": has_metric_anchor_below(
                    rect_to_tuple(getattr(target, "rect", None)),
                    text_nodes,
                ),
            }
            for index, target in enumerate(final_targets, 1)
        ],
        "all_text_nodes": [
            {
                "depth": node.depth,
                "path": node.path,
                "text": node.text,
                "rect": list(node.rect),
                "control_type": node.control_type,
                "class_name": node.class_name,
                "hwnd": node.hwnd,
            }
            for node in text_nodes
        ],
    }


def collect_text_nodes(home_window: Any, *, max_depth: int, max_nodes: int) -> list[TextNode]:
    nodes: list[TextNode] = []
    queue: deque[tuple[Any, int, str]] = deque([(home_window, 0, "0")])

    while queue and len(nodes) < max_nodes:
        control, depth, path = queue.popleft()
        text = control_text(control)
        rect = rect_to_tuple(safe_get(control, "BoundingRectangle", None))
        if text:
            nodes.append(
                TextNode(
                    depth=depth,
                    path=path,
                    text=text,
                    rect=rect,
                    control_type=str(safe_get(control, "ControlTypeName", "") or ""),
                    class_name=str(safe_get(control, "ClassName", "") or ""),
                    hwnd=safe_int(safe_get(control, "NativeWindowHandle", 0)),
                )
            )

        if depth >= max_depth:
            continue
        children = safe_call(control.GetChildren) or []
        for child_index, child in enumerate(children):
            if len(nodes) + len(queue) >= max_nodes:
                break
            queue.append((child, depth + 1, f"{path}.{child_index}"))
    return nodes


def analyze_text_node(
    node: TextNode,
    all_nodes: list[TextNode],
    *,
    nav_bottom: int | None,
    markers: list[dict[str, Any]],
    final_targets: list[Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    if not valid_rect(node.rect):
        reasons.append("no_valid_rect")
    if not looks_like_article_title(node.text):
        reasons.append("not_like_article_title")
    if nav_bottom is not None and node.rect[1] < nav_bottom:
        reasons.append("above_home_nav")
    excluded_marker = current_excluded_marker(node.rect, markers)
    if excluded_marker:
        reasons.append(f"in_excluded_section:{excluded_marker}")
    if not has_metric_anchor_below(node.rect, all_nodes):
        reasons.append("no_metric_anchor_below_120px")

    in_final_targets = any(
        normalize_title(str(getattr(target, "title", "") or "")) == normalize_title(node.text)
        and rect_to_tuple(getattr(target, "rect", None)) == node.rect
        for target in final_targets
    )
    if in_final_targets:
        reasons.append("accepted_final_click_target")

    return {
        "text": node.text,
        "rect": list(node.rect),
        "depth": node.depth,
        "path": node.path,
        "control_type": node.control_type,
        "class_name": node.class_name,
        "hwnd": node.hwnd,
        "looks_like_article_title": looks_like_article_title(node.text),
        "has_valid_rect": valid_rect(node.rect),
        "has_metric_anchor_below": has_metric_anchor_below(node.rect, all_nodes),
        "metric_nodes_below": metric_nodes_below(node.rect, all_nodes),
        "exclude_reasons_or_status": reasons,
    }


def summarize_control(control: Any) -> dict[str, Any]:
    return {
        "name": str(safe_get(control, "Name", "") or ""),
        "class_name": str(safe_get(control, "ClassName", "") or ""),
        "control_type": str(safe_get(control, "ControlTypeName", "") or ""),
        "hwnd": safe_int(safe_get(control, "NativeWindowHandle", 0)),
        "process_id": safe_int(safe_get(control, "ProcessId", 0)),
        "rect": list(rect_to_tuple(safe_get(control, "BoundingRectangle", None))),
    }


def looks_like_article_title(text: str) -> bool:
    value = normalize_candidate_text(text)
    if not (2 <= len(value) <= 80):
        return False
    if value in {
        "公众号",
        "服务号",
        "微信",
        "Weixin",
        "WeChat",
        "MMUIRenderSubWindowHW",
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
    if is_article_date_anchor(value):
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
    if looks_like_profile_name(value):
        return False
    if looks_like_profile_description(value):
        return False
    return True


def detect_nav_row_bottom(nodes: list[TextNode]) -> int | None:
    nav_rects = [node.rect for node in nodes if normalize_candidate_text(node.text) in {"全部", "贴图", "文章", "视频号"} and valid_rect(node.rect)]
    if not nav_rects:
        return None
    nav_top = min(rect[1] for rect in nav_rects)
    nav_row_rects = [rect for rect in nav_rects if rect[1] <= nav_top + 40]
    return max(rect[3] for rect in (nav_row_rects or nav_rects))


def is_article_date_anchor(value: str) -> bool:
    return value in {"今天", "昨天"} or bool(re.fullmatch(r"(?:\d{4}年)?\d{1,2}月\d{1,2}日", value))


def build_section_markers(nodes: list[TextNode], *, nav_bottom: int | None) -> list[dict[str, Any]]:
    if nav_bottom is None:
        return []
    markers = []
    for node in nodes:
        label = normalize_candidate_text(node.text)
        if label not in {"贴图", "文章", "视频号"}:
            continue
        if not valid_rect(node.rect) or node.rect[1] < nav_bottom + 24:
            continue
        markers.append({"label": label, "rect": list(node.rect), "top": node.rect[1]})
    markers.sort(key=lambda item: (int(item["top"]), item["rect"][0], item["rect"][2]))
    return markers


def current_excluded_marker(rect: tuple[int, int, int, int], markers: list[dict[str, Any]]) -> str:
    if not valid_rect(rect):
        return ""
    current = ""
    for marker in markers:
        if int(marker.get("top") or 0) > rect[1]:
            break
        current = str(marker.get("label") or "")
    if current in {"贴图", "视频号"}:
        return current
    return ""


def has_metric_anchor_below(rect: tuple[int, int, int, int], nodes: list[TextNode]) -> bool:
    return bool(metric_nodes_below(rect, nodes))


def metric_nodes_below(rect: tuple[int, int, int, int], nodes: list[TextNode]) -> list[dict[str, Any]]:
    if not valid_rect(rect):
        return []
    left, _top, right, bottom = rect
    matches = []
    for node in nodes:
        text = normalize_candidate_text(node.text)
        node_left, node_top, node_right, _node_bottom = node.rect
        if not re.search(r"阅读\s*[\d.]+(?:万)?\+?.*赞\s*\d+", text):
            continue
        if not (0 <= node_top - bottom <= 120):
            continue
        if abs(node_left - left) <= 80 or min(right, node_right) > max(left, node_left):
            matches.append({"text": node.text, "rect": list(node.rect), "distance_px": node_top - bottom})
    return matches


def valid_rect(rect: tuple[int, int, int, int]) -> bool:
    left, top, right, bottom = rect
    return right > left and bottom > top and (right - left) >= 20 and (bottom - top) >= 10


def control_text(control: Any) -> str:
    for attr_name in ("Name", "Value"):
        value = str(safe_get(control, attr_name, "") or "").strip()
        if value:
            return value
    return ""


def looks_like_profile_name(value: str) -> bool:
    if len(value) > 5:
        return False
    if re.search(r"[，。！？、；：“”‘’《》（）()\[\]【】,.!?;:]", value):
        return False
    return bool(re.search(r"[\u4e00-\u9fff]", value))


def looks_like_profile_description(value: str) -> bool:
    if any(marker in value for marker in ("官方账号", "官方公众号", "官方微信", "订阅号", "服务号", "资讯号")) and re.search(
        r"[。，、；;！!？?]",
        value,
    ):
        return True
    if len(value) > 18:
        return False
    if "、" not in value or not value.endswith("。"):
        return False
    if re.search(r"[\d“”《》【】]", value):
        return False
    return True


def normalize_title(text: str) -> str:
    return "".join(str(text or "").split())


def safe_get(obj: Any, attr_name: str, default: Any = "") -> Any:
    try:
        return getattr(obj, attr_name)
    except Exception:
        return default


def safe_call(func: Any, *args: Any) -> Any:
    try:
        return func(*args)
    except Exception:
        return None


def safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def build_console_summary(report: dict[str, Any], output_path: Path) -> dict[str, Any]:
    keyword_nodes = report.get("keyword_nodes") if isinstance(report.get("keyword_nodes"), list) else []
    final_targets = report.get("final_click_targets") if isinstance(report.get("final_click_targets"), list) else []
    return {
        "ok": report.get("ok"),
        "reason": report.get("reason", ""),
        "home_window": report.get("home_window", {}),
        "keyword_nodes": keyword_nodes,
        "final_click_targets": final_targets,
        "raw_title_candidate_count": len(report.get("raw_title_candidates") or []),
        "final_click_target_count": len(final_targets),
        "output_path": str(output_path),
    }


if __name__ == "__main__":
    main()
