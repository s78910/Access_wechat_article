from __future__ import annotations

from collections import Counter, deque
from datetime import datetime
import json
from pathlib import Path
import sys
import time
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.modules.window.article_card_reader import UiaArticleCardReader
from src.modules.window.uia_article_group_parser import (
    is_uia_date_text,
    is_uia_metric_text,
)
from src.modules.window.wechat_document_reader import find_wechat_document_control
from src.modules.window.wechat_home_reader import WechatHomeReader
from src.modules.window.wechat_home_window_finder import (
    WechatHomeWindowMinimized,
    find_wechat_home_window,
    rect_to_tuple,
)


Rect = tuple[int, int, int, int]

# 本脚本只读取当前主页 UIA 树，不激活窗口、不滚动、不点击�?CONFIG = {
    "window_find_timeout_seconds": 3.0,
    "max_depth": 16,
    "max_nodes": 8000,
    "output_root": PROJECT_ROOT / "data" / "tmp",
    "tree_file_name": "tree.txt",
    "report_file_name": "report.json",
}


def main() -> int:
    _configure_console()
    started_at = time.perf_counter()
    run_dir = _create_run_dir(Path(CONFIG["output_root"]))
    report: dict[str, Any] = {
        "status": "running",
        "startedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "readOnly": True,
        "actionsNotPerformed": ["激活窗�?, "滚动页面", "移动鼠标", "点击", "键盘输入"],
        "outputDirectory": str(run_dir),
    }

    try:
        home_window = find_wechat_home_window(
            timeout_seconds=float(CONFIG["window_find_timeout_seconds"]),
        )
        if home_window is None:
            raise RuntimeError("未找到已打开的微信公众号主页窗口")

        report["window"] = {
            "handle": home_window.handle,
            "title": home_window.title,
            "className": home_window.class_name,
            "processName": home_window.process_name,
            "rect": list(home_window.rect),
            "visible": home_window.visible,
            "minimized": home_window.is_minimized,
        }

        document = find_wechat_document_control(
            home_window.control,
            max_depth=int(CONFIG["max_depth"]),
        )
        if document is None:
            raise RuntimeError("已找到主页窗口，但没有找�?DocumentControl")

        document_rect = rect_to_tuple(_safe_get(document, "BoundingRectangle", None))
        viewport = _rect_intersection(home_window.rect, document_rect)
        if not _valid_rect(viewport):
            raise RuntimeError("DocumentControl 与主页窗口没有有效的可视区域交集")

        nodes, truncated = _snapshot_tree(
            document,
            viewport=viewport,
            max_depth=int(CONFIG["max_depth"]),
            max_nodes=int(CONFIG["max_nodes"]),
        )
        _attach_descendant_text(nodes)

        home_info_error = ""
        try:
            home_info = WechatHomeReader().read(home_window)
            account_name = home_info.account_name
        except Exception as exc:
            account_name = ""
            home_info_error = f"{type(exc).__name__}: {exc}"

        observation = UiaArticleCardReader(
            max_depth=int(CONFIG["max_depth"]),
            max_nodes=int(CONFIG["max_nodes"]),
        ).read_viewport(home_window, account_name=account_name)

        group_candidates = _date_group_candidates(nodes)
        article_targets = [_target_to_dict(index, target) for index, target in enumerate(observation.targets, 1)]
        report.update(
            {
                "status": "success",
                "durationSeconds": round(time.perf_counter() - started_at, 3),
                "accountName": account_name,
                "accountNameError": home_info_error,
                "document": {
                    "rect": list(document_rect),
                    "viewport": list(viewport),
                    "isOffscreen": bool(_safe_get(document, "IsOffscreen", False)),
                },
                "tree": {
                    "nodeCount": len(nodes),
                    "truncated": truncated,
                    "maxDepth": max((int(node["depth"]) for node in nodes), default=0),
                    "controlTypeStats": _control_type_stats(nodes),
                    "coordinateStats": _coordinate_stats(nodes),
                    "nodes": nodes,
                },
                "dateGroupCandidates": group_candidates,
                "articleParser": {
                    "articleCount": len(article_targets),
                    "loading": observation.loading,
                    "visibleRangeCount": observation.range_count,
                    "visibleSignature": list(observation.visible_signature),
                    "targets": article_targets,
                    "discarded": list(observation.decisions),
                },
            }
        )
    except WechatHomeWindowMinimized as exc:
        report.update(
            {
                "status": "failed",
                "error": "检测到公众号主页窗口处于最小化状�?,
                "window": {
                    "handle": exc.window.handle,
                    "title": exc.window.title,
                    "rect": list(exc.window.rect),
                    "minimized": True,
                },
            }
        )
    except Exception as exc:
        report.update(
            {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
    finally:
        report["durationSeconds"] = round(time.perf_counter() - started_at, 3)
        _write_report(run_dir, report)

    _print_summary(report)
    return 0 if report.get("status") == "success" else 1


def _snapshot_tree(
    root: Any,
    *,
    viewport: Rect,
    max_depth: int,
    max_nodes: int,
) -> tuple[list[dict[str, Any]], bool]:
    nodes: list[dict[str, Any]] = []
    queue: deque[tuple[Any, int, int | None, str]] = deque([(root, 0, None, "0")])

    while queue and len(nodes) < max_nodes:
        control, depth, parent_index, path = queue.popleft()
        children = _safe_children(control) if depth < max_depth else []
        rect = rect_to_tuple(_safe_get(control, "BoundingRectangle", None))
        center = _rect_center(rect) if _valid_rect(rect) else None
        node = {
            "index": len(nodes),
            "parentIndex": parent_index,
            "path": path,
            "depth": depth,
            "controlType": str(_safe_get(control, "ControlTypeName", "") or ""),
            "name": str(_safe_get(control, "Name", "") or ""),
            "automationId": str(_safe_get(control, "AutomationId", "") or ""),
            "className": str(_safe_get(control, "ClassName", "") or ""),
            "frameworkId": str(_safe_get(control, "FrameworkId", "") or ""),
            "rect": list(rect),
            "center": list(center) if center is not None else None,
            "coordinateState": _coordinate_state(rect, viewport),
            "isOffscreen": bool(_safe_get(control, "IsOffscreen", False)),
            "isEnabled": bool(_safe_get(control, "IsEnabled", False)),
            "isKeyboardFocusable": bool(_safe_get(control, "IsKeyboardFocusable", False)),
            "hasKeyboardFocus": bool(_safe_get(control, "HasKeyboardFocus", False)),
            "nativeWindowHandle": _safe_int(_safe_get(control, "NativeWindowHandle", 0)),
            "childCount": len(children),
            "childIndexes": [],
        }
        node_index = len(nodes)
        nodes.append(node)
        if parent_index is not None:
            nodes[parent_index]["childIndexes"].append(node_index)

        for child_position, child in enumerate(children):
            queue.append((child, depth + 1, node_index, f"{path}.{child_position}"))

    return nodes, bool(queue)


def _attach_descendant_text(nodes: list[dict[str, Any]]) -> None:
    descendant_text_indexes: list[list[int]] = [[] for _ in nodes]
    for index in range(len(nodes) - 1, -1, -1):
        node = nodes[index]
        child_indexes = [int(value) for value in node["childIndexes"]]
        control_type = str(node["controlType"] or "").lower()
        name = str(node["name"] or "").strip()
        has_text_child = any(
            str(nodes[child_index]["controlType"] or "").lower() == "textcontrol"
            for child_index in child_indexes
        )
        if control_type == "textcontrol" and name and not has_text_child:
            descendant_text_indexes[index] = [index]
        else:
            descendant_text_indexes[index] = [
                text_index
                for child_index in child_indexes
                for text_index in descendant_text_indexes[child_index]
            ]

        # 完整索引用于分组分析，预览文本限制数量，避免 JSON 被重复内容撑大�?        node["descendantTextIndexes"] = descendant_text_indexes[index]
        node["descendantTextPreview"] = [
            str(nodes[text_index]["name"])
            for text_index in descendant_text_indexes[index][:30]
        ]


def _date_group_candidates(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for node in nodes:
        if str(node["controlType"] or "").lower() != "groupcontrol":
            continue

        date_children: list[dict[str, Any]] = []
        article_children: list[dict[str, Any]] = []
        for child_index_value in node["childIndexes"]:
            child_index = int(child_index_value)
            text_indexes = [int(value) for value in nodes[child_index]["descendantTextIndexes"]]
            date_indexes = [
                index for index in text_indexes if is_uia_date_text(str(nodes[index]["name"]))
            ]
            metric_indexes = [
                index for index in text_indexes if is_uia_metric_text(str(nodes[index]["name"]))
            ]
            if len(date_indexes) == 1 and not metric_indexes:
                date_children.append(
                    _group_child_detail(nodes, child_index, date_indexes[0], "date")
                )
            if len(metric_indexes) == 1 and not date_indexes:
                article_children.append(
                    _group_child_detail(nodes, child_index, metric_indexes[0], "article")
                )

        if not date_children and not article_children:
            continue

        date_position = _child_position(node, date_children[0]["childIndex"]) if len(date_children) == 1 else -1
        article_positions = [
            _child_position(node, article["childIndex"]) for article in article_children
        ]
        accepted = (
            len(date_children) == 1
            and bool(article_children)
            and all(position > date_position for position in article_positions)
        )
        result.append(
            {
                "groupIndex": node["index"],
                "path": node["path"],
                "rect": node["rect"],
                "coordinateState": node["coordinateState"],
                "acceptedByCurrentStructureRule": accepted,
                "dateChildren": date_children,
                "articleChildren": article_children,
            }
        )
    return result


def _group_child_detail(
    nodes: list[dict[str, Any]],
    child_index: int,
    marker_index: int,
    kind: str,
) -> dict[str, Any]:
    text_indexes = [int(value) for value in nodes[child_index]["descendantTextIndexes"]]
    return {
        "kind": kind,
        "childIndex": child_index,
        "childPath": nodes[child_index]["path"],
        "childRect": nodes[child_index]["rect"],
        "markerIndex": marker_index,
        "markerText": nodes[marker_index]["name"],
        "markerRect": nodes[marker_index]["rect"],
        "markerCoordinateState": nodes[marker_index]["coordinateState"],
        "leafTexts": [
            {
                "index": text_index,
                "text": nodes[text_index]["name"],
                "rect": nodes[text_index]["rect"],
                "coordinateState": nodes[text_index]["coordinateState"],
            }
            for text_index in text_indexes
        ],
    }


def _target_to_dict(index: int, target: Any) -> dict[str, Any]:
    return {
        "index": index,
        "dateText": target.date_text,
        "publishedDate": target.published_date,
        "dateRect": _json_rect(target.date_rect),
        "title": target.title,
        "rawTitle": target.raw_title,
        "titleRect": _json_rect(target.title_rect),
        "metricText": target.metric_text,
        "metricRect": _json_rect(target.metric_rect),
        "clickPoint": [target.click_x, target.click_y],
        "fingerprint": target.fingerprint,
    }


def _control_type_stats(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(str(node["controlType"] or "<empty>") for node in nodes)
    return [
        {"controlType": control_type, "count": count}
        for control_type, count in counts.most_common()
    ]


def _coordinate_stats(nodes: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(node["coordinateState"]) for node in nodes)
    return {
        "valid": sum(count for state, count in counts.items() if state != "invalid"),
        "fullyVisible": counts["fully-visible"],
        "partiallyVisible": counts["partially-visible"],
        "outsideViewport": counts["outside-viewport"],
        "invalid": counts["invalid"],
    }


def _write_report(run_dir: Path, report: dict[str, Any]) -> None:
    report_path = run_dir / str(CONFIG["report_file_name"])
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    tree_path = run_dir / str(CONFIG["tree_file_name"])
    lines: list[str] = []
    for node in report.get("tree", {}).get("nodes", []):
        indent = "  " * int(node["depth"])
        text = str(node["name"] or "").replace("\r", " ").replace("\n", " ")
        lines.append(
            f"{indent}[{node['index']:04d}] {node['controlType'] or '<empty>'} "
            f"name={text!r} rect={tuple(node['rect'])} "
            f"state={node['coordinateState']} offscreen={node['isOffscreen']} "
            f"automation_id={node['automationId']!r}"
        )
    tree_path.write_text("\n".join(lines), encoding="utf-8")


def _print_summary(report: dict[str, Any]) -> None:
    related_groups = list(report.get("dateGroupCandidates", []))
    accepted_groups = [
        group
        for group in related_groups
        if group.get("acceptedByCurrentStructureRule") is True
    ]
    print(json.dumps(
        {
            "status": report.get("status"),
            "error": report.get("error", ""),
            "durationSeconds": report.get("durationSeconds"),
            "outputDirectory": report.get("outputDirectory"),
            "window": report.get("window", {}),
            "accountName": report.get("accountName", ""),
            "document": report.get("document", {}),
            "treeSummary": {
                "nodeCount": report.get("tree", {}).get("nodeCount", 0),
                "truncated": report.get("tree", {}).get("truncated", False),
                "maxDepth": report.get("tree", {}).get("maxDepth", 0),
                "controlTypeStats": report.get("tree", {}).get("controlTypeStats", []),
                "coordinateStats": report.get("tree", {}).get("coordinateStats", {}),
            },
            "relatedGroupCount": len(related_groups),
            "acceptedDateGroupCount": len(accepted_groups),
            "acceptedDateGroups": [
                {
                    "groupIndex": group.get("groupIndex"),
                    "rect": group.get("rect"),
                    "coordinateState": group.get("coordinateState"),
                    "dateText": (
                        group.get("dateChildren", [{}])[0].get("markerText", "")
                        if group.get("dateChildren")
                        else ""
                    ),
                    "articleCount": len(group.get("articleChildren", [])),
                }
                for group in accepted_groups
            ],
            "articleTargets": report.get("articleParser", {}).get("targets", []),
            "discarded": report.get("articleParser", {}).get("discarded", []),
        },
        ensure_ascii=False,
        indent=2,
        default=str,
    ))


def _create_run_dir(output_root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    run_dir = output_root / f"uia-home-probe-{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _coordinate_state(rect: Rect, viewport: Rect) -> str:
    if not _valid_rect(rect):
        return "invalid"
    if _rect_fully_inside(rect, viewport):
        return "fully-visible"
    if _rect_intersects(rect, viewport):
        return "partially-visible"
    return "outside-viewport"


def _rect_intersection(left: Rect, right: Rect) -> Rect:
    return (
        max(left[0], right[0]),
        max(left[1], right[1]),
        min(left[2], right[2]),
        min(left[3], right[3]),
    )


def _rect_fully_inside(rect: Rect, viewport: Rect) -> bool:
    return (
        _valid_rect(rect)
        and rect[0] >= viewport[0]
        and rect[1] >= viewport[1]
        and rect[2] <= viewport[2]
        and rect[3] <= viewport[3]
    )


def _rect_intersects(rect: Rect, viewport: Rect) -> bool:
    return (
        _valid_rect(rect)
        and rect[0] < viewport[2]
        and rect[2] > viewport[0]
        and rect[1] < viewport[3]
        and rect[3] > viewport[1]
    )


def _rect_center(rect: Rect) -> tuple[int, int]:
    return ((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)


def _valid_rect(rect: Rect) -> bool:
    return rect[2] > rect[0] and rect[3] > rect[1]


def _child_position(parent: dict[str, Any], child_index: int) -> int:
    try:
        return [int(value) for value in parent["childIndexes"]].index(int(child_index))
    except ValueError:
        return -1


def _json_rect(value: Any) -> list[int] | None:
    if value is None:
        return None
    rect = rect_to_tuple(value)
    return list(rect) if _valid_rect(rect) else None


def _safe_children(control: Any) -> list[Any]:
    try:
        return list(control.GetChildren() or [])
    except Exception:
        return []


def _safe_get(value: Any, name: str, default: Any) -> Any:
    try:
        return getattr(value, name)
    except Exception:
        return default


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    raise SystemExit(main())
