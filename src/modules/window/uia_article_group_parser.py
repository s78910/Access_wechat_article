from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import re
import unicodedata
from typing import Any

from src.modules.window.wechat_home_window_finder import rect_to_tuple


Rect = tuple[int, int, int, int]

_ARTICLE_CONTROL_TEXT = frozenset(
    {
        "公众号",
        "服务号",
        "订阅号",
        "微信",
        "weixin",
        "wechat",
        "全部",
        "贴图",
        "文章",
        "视频",
        "视频号",
        "展开",
        "收起",
        "置顶",
        "加载更多",
        "正在加载...",
        "发消息",
        "已关注",
    }
)


@dataclass(frozen=True, slots=True)
class UiaArticleCardNode:
    """从一个 UIA 文章卡片子树中提取出的单篇文章信息。"""

    date_text: str
    date_rect: Rect | None
    raw_title: str
    title_rect: Rect | None
    metric_text: str
    metric_rect: Rect
    metric_control: Any
    metric_automation_id: str = ""


@dataclass(frozen=True, slots=True)
class UiaArticleTreeObservation:
    cards: tuple[UiaArticleCardNode, ...]
    decisions: tuple[dict[str, Any], ...]
    group_count: int = 0
    node_count: int = 0


@dataclass(slots=True)
class _ControlNode:
    control: Any
    depth: int
    control_type: str
    name: str
    rect: Rect
    automation_id: str
    children: list[int]


class UiaArticleGroupParser:
    """按 UIA 父子关系解析“日期组 -> 文章卡片”，不读取 TextPattern。"""

    def __init__(self, *, max_depth: int = 14, max_nodes: int = 5000) -> None:
        self.max_depth = max(1, int(max_depth))
        self.max_nodes = max(1, int(max_nodes))

    def parse(
        self,
        document: Any,
        *,
        viewport: Rect,
        content_top: int,
    ) -> UiaArticleTreeObservation:
        nodes = _snapshot_tree(
            document,
            max_depth=self.max_depth,
            max_nodes=self.max_nodes,
        )
        if not nodes or not _valid_rect(viewport):
            return UiaArticleTreeObservation((), (), node_count=len(nodes))

        descendant_leaves = _descendant_text_leaves(nodes)
        cards: list[UiaArticleCardNode] = []
        decisions: list[dict[str, Any]] = []
        group_count = 0
        seen_metrics: set[tuple[str, Rect]] = set()

        for group_index, group in enumerate(nodes):
            if group.control_type != "groupcontrol":
                continue
            parsed_group = _parse_date_group(
                group_index,
                nodes=nodes,
                descendant_leaves=descendant_leaves,
            )
            if parsed_group is None:
                continue
            date_leaf_index, card_children = parsed_group
            group_count += 1
            date_leaf = nodes[date_leaf_index]
            date_rect = (
                date_leaf.rect
                if _rect_fully_inside(date_leaf.rect, viewport)
                and date_leaf.rect[3] > content_top
                else None
            )

            for card_child_index, metric_leaf_index in card_children:
                metric_leaf = nodes[metric_leaf_index]
                metric_key = (metric_leaf.name, metric_leaf.rect)
                if metric_key in seen_metrics:
                    continue
                seen_metrics.add(metric_key)

                title_leaf_index = _select_title_leaf(
                    card_child_index,
                    metric_leaf_index=metric_leaf_index,
                    nodes=nodes,
                    descendant_leaves=descendant_leaves,
                )
                title_leaf = (
                    nodes[title_leaf_index]
                    if title_leaf_index is not None
                    else None
                )
                raw_title = title_leaf.name if title_leaf is not None else ""
                title_rect = (
                    title_leaf.rect
                    if title_leaf is not None and _valid_rect(title_leaf.rect)
                    else None
                )

                metric_visible = (
                    metric_leaf.rect[1] >= content_top
                    and _rect_fully_inside(metric_leaf.rect, viewport)
                )
                if not metric_visible:
                    card_rect = nodes[card_child_index].rect
                    if _rect_intersects(card_rect, viewport) or _rect_intersects(
                        metric_leaf.rect,
                        viewport,
                    ):
                        decisions.append(
                            _decision(
                                reason="阅读指标没有完整位于主页可视区",
                                date_text=date_leaf.name,
                                title_fragment=raw_title,
                                title_rect=title_rect,
                                metric_text=metric_leaf.name,
                                metric_rect=(
                                    metric_leaf.rect
                                    if _valid_rect(metric_leaf.rect)
                                    else None
                                ),
                            )
                        )
                    continue

                cards.append(
                    UiaArticleCardNode(
                        date_text=date_leaf.name,
                        date_rect=date_rect,
                        raw_title=raw_title,
                        title_rect=title_rect,
                        metric_text=metric_leaf.name,
                        metric_rect=metric_leaf.rect,
                        metric_control=metric_leaf.control,
                        metric_automation_id=metric_leaf.automation_id,
                    )
                )

        ordered_cards = tuple(
            sorted(
                cards,
                key=lambda item: (
                    item.metric_rect[1],
                    item.metric_rect[0],
                    item.raw_title,
                ),
            )
        )
        return UiaArticleTreeObservation(
            cards=ordered_cards,
            decisions=tuple(decisions),
            group_count=group_count,
            node_count=len(nodes),
        )


def normalize_uia_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or ""))
    value = value.replace("\u200b", "").replace("\ufeff", "").strip()
    return re.sub(r"\s+", " ", value)


def is_uia_date_text(text: str) -> bool:
    value = normalize_uia_text(text)
    return value in {"今天", "昨天"} or bool(
        re.fullmatch(
            r"(?:星期[一二三四五六日天]|(?:\d{4}年)?\d{1,2}月\d{1,2}日)",
            value,
        )
    )


def is_uia_metric_text(text: str) -> bool:
    value = normalize_uia_text(text)
    return bool(
        re.search(
            r"^阅读\s*[\d.]+(?:万)?\+?(?:.*赞\s*[\d.]+(?:万)?\+?)?",
            value,
        )
    )


def _snapshot_tree(
    root: Any,
    *,
    max_depth: int,
    max_nodes: int,
) -> list[_ControlNode]:
    result: list[_ControlNode] = []
    queue: deque[tuple[Any, int, int | None]] = deque([(root, 0, None)])
    while queue and len(result) < max_nodes:
        control, depth, parent_index = queue.popleft()
        node_index = len(result)
        result.append(
            _ControlNode(
                control=control,
                depth=depth,
                control_type=str(
                    _safe_get(control, "ControlTypeName", "") or ""
                ).lower(),
                name=normalize_uia_text(
                    str(_safe_get(control, "Name", "") or "")
                ),
                rect=rect_to_tuple(
                    _safe_get(control, "BoundingRectangle", None)
                ),
                automation_id=str(
                    _safe_get(control, "AutomationId", "") or ""
                ),
                children=[],
            )
        )
        if parent_index is not None:
            result[parent_index].children.append(node_index)
        if depth >= max_depth:
            continue
        for child in _safe_children(control):
            queue.append((child, depth + 1, node_index))
    return result


def _descendant_text_leaves(nodes: list[_ControlNode]) -> list[tuple[int, ...]]:
    result: list[tuple[int, ...]] = [() for _ in nodes]
    for index in range(len(nodes) - 1, -1, -1):
        node = nodes[index]
        has_text_child = any(
            nodes[child_index].control_type == "textcontrol"
            for child_index in node.children
        )
        if node.control_type == "textcontrol" and not has_text_child and node.name:
            result[index] = (index,)
            continue
        result[index] = tuple(
            leaf_index
            for child_index in node.children
            for leaf_index in result[child_index]
        )
    return result


def _parse_date_group(
    group_index: int,
    *,
    nodes: list[_ControlNode],
    descendant_leaves: list[tuple[int, ...]],
) -> tuple[int, tuple[tuple[int, int], ...]] | None:
    group = nodes[group_index]
    date_rows: list[tuple[int, int]] = []
    article_children: list[tuple[int, int]] = []

    for child_index in group.children:
        leaf_indices = descendant_leaves[child_index]
        date_leaves = [
            leaf_index
            for leaf_index in leaf_indices
            if is_uia_date_text(nodes[leaf_index].name)
        ]
        metric_leaves = [
            leaf_index
            for leaf_index in leaf_indices
            if is_uia_metric_text(nodes[leaf_index].name)
        ]
        # 日期行和文章卡片必须是日期组的不同直接子节点。
        if len(date_leaves) == 1 and not metric_leaves:
            date_rows.append((child_index, date_leaves[0]))
        if len(metric_leaves) == 1 and not date_leaves:
            article_children.append((child_index, metric_leaves[0]))

    if len(date_rows) != 1 or not article_children:
        return None
    date_child_index, date_leaf_index = date_rows[0]
    if any(
        group.children.index(card_child_index)
        <= group.children.index(date_child_index)
        for card_child_index, _metric_leaf_index in article_children
    ):
        return None
    return date_leaf_index, tuple(article_children)


def _select_title_leaf(
    card_index: int,
    *,
    metric_leaf_index: int,
    nodes: list[_ControlNode],
    descendant_leaves: list[tuple[int, ...]],
) -> int | None:
    metric = nodes[metric_leaf_index]
    candidates: list[int] = []
    for leaf_index in descendant_leaves[card_index]:
        if leaf_index == metric_leaf_index:
            continue
        leaf = nodes[leaf_index]
        if not _is_title_candidate(leaf.name):
            continue
        if _valid_rect(leaf.rect) and leaf.rect[1] > metric.rect[1]:
            continue
        if (
            _valid_rect(leaf.rect)
            and _valid_rect(metric.rect)
            and not _horizontal_overlap(leaf.rect, metric.rect)
        ):
            continue
        candidates.append(leaf_index)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda leaf_index: (
            nodes[leaf_index].rect[1],
            nodes[leaf_index].depth,
            len(nodes[leaf_index].name),
        ),
    )


def _is_title_candidate(text: str) -> bool:
    value = normalize_uia_text(text)
    if not value or len(value) > 240:
        return False
    if value.lower() in _ARTICLE_CONTROL_TEXT or value in _ARTICLE_CONTROL_TEXT:
        return False
    if is_uia_date_text(value) or is_uia_metric_text(value):
        return False
    if value.startswith(("视频号", "贴图")):
        return False
    if re.fullmatch(r"(?=.*\d)[\d.]+(?:万)?\+?", value):
        return False
    if re.search(r"\d+\s*(?:篇原创|个朋友关注)", value):
        return False
    return True


def _decision(
    *,
    reason: str,
    date_text: str,
    title_fragment: str,
    title_rect: Rect | None,
    metric_text: str,
    metric_rect: Rect | None,
) -> dict[str, Any]:
    return {
        "status": "discarded",
        "reason": reason,
        "titleFragment": title_fragment,
        "dateText": date_text,
        "metricText": metric_text,
        "titleRect": title_rect,
        "metricRect": metric_rect,
    }


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


def _valid_rect(rect: Rect) -> bool:
    return rect[2] > rect[0] and rect[3] > rect[1]


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


def _horizontal_overlap(left: Rect, right: Rect) -> bool:
    return max(left[0], right[0]) < min(left[2], right[2])


__all__ = [
    "UiaArticleCardNode",
    "UiaArticleGroupParser",
    "UiaArticleTreeObservation",
    "is_uia_date_text",
    "is_uia_metric_text",
    "normalize_uia_text",
]
