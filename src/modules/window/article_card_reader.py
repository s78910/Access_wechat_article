from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import hashlib
import re
import unicodedata
from typing import Any

from src.domain.models import ArticleTarget
from src.modules.window.wechat_home_window_finder import rect_to_tuple
from src.modules.window.wechat_document_reader import (
    document_text_lines,
    find_wechat_document_control,
)
from src.modules.window.window_models import WindowInfo


EXCLUDED_TEXT = frozenset(
    {
        "公众号",
        "服务号",
        "订阅号",
        "微信",
        "weixin",
        "wechat",
        "贴图",
        "视频",
        "视频号",
        "文章",
        "全部",
        "今天",
        "昨天",
        "展开",
        "置顶",
        "发消息",
        "已关注",
        "最小化",
        "最大化",
        "还原",
        "关闭",
    }
)


@dataclass(frozen=True, slots=True)
class _TextNode:
    text: str
    rect: tuple[int, int, int, int]
    hwnd: int
    automation_id: str
    control: Any


@dataclass(frozen=True, slots=True)
class ArticleViewportObservation:
    """一次可视区域观测；只有 targets 中的项目才允许进入点击候选。"""

    targets: tuple[ArticleTarget, ...]
    visible_signature: tuple[str, ...]
    loading: bool = False


class UiaArticleCardReader:
    """从公众号主页 UIA 树读取当前可见文章卡片，不执行点击。"""

    def __init__(self, *, max_depth: int = 12, max_nodes: int = 5000) -> None:
        self.max_depth = max(1, int(max_depth))
        self.max_nodes = max(1, int(max_nodes))

    def read(self, home_window: WindowInfo, *, account_name: str = "") -> list[ArticleTarget]:
        return list(
            self.read_viewport(
                home_window,
                account_name=account_name,
            ).targets
        )

    def read_viewport(
        self,
        home_window: WindowInfo,
        *,
        account_name: str = "",
    ) -> ArticleViewportObservation:
        if home_window.control is None or not home_window.has_valid_rect:
            return ArticleViewportObservation((), ())
        nodes = self._collect_text_nodes(
            home_window.control,
            viewport=home_window.rect,
        )
        node_signature = _node_visible_signature(nodes)
        metrics = [node for node in nodes if _is_metric_text(node.text)]
        # 文章主页卡片应带有“阅读…赞…”指标锚点。没有锚点时通常是文章详情页或
        # Chromium 工具栏；禁止退化为“所有可读文本都是文章”的宽松模式。
        if not metrics:
            document = find_wechat_document_control(home_window.control)
            if document is None:
                return ArticleViewportObservation(
                    (),
                    node_signature,
                    _signature_has_loading(node_signature),
                )
            visible_ranges = _get_visible_ranges(document)
            visible_signature = _visible_range_signature(visible_ranges)
            targets = _visible_range_targets(
                document,
                account_name=account_name,
                home_window=home_window,
                visible_ranges=visible_ranges,
            )
            return ArticleViewportObservation(
                tuple(targets),
                visible_signature,
                _signature_has_loading(visible_signature),
            )
        targets: list[ArticleTarget] = []
        seen: set[tuple[str, tuple[int, int, int, int]]] = set()
        matched_metric_rects: set[tuple[int, int, int, int]] = set()
        for node in nodes:
            if not is_article_title_text(node.text):
                continue
            matched_metric = next(
                (
                    metric
                    for metric in metrics
                    if _metric_belongs_to_title(node.rect, metric.rect)
                ),
                None,
            )
            if matched_metric is None:
                continue
            key = (normalize_window_text(node.text), node.rect)
            if key in seen:
                continue
            seen.add(key)
            matched_metric_rects.add(matched_metric.rect)
            click_x, click_y = _rect_center(matched_metric.rect)
            targets.append(
                ArticleTarget(
                    account_name=account_name,
                    title=node.text.strip(),
                    click_x=click_x,
                    click_y=click_y,
                    home_window_handle=node.hwnd or home_window.handle,
                    fingerprint=_build_fingerprint(node.text, node.automation_id),
                    control=matched_metric.control,
                )
            )
        targets.extend(
            _metric_only_article_targets(
                nodes,
                metrics,
                matched_metric_rects=matched_metric_rects,
                seen=seen,
                account_name=account_name,
                home_window=home_window,
            )
        )
        ordered = sorted(targets, key=lambda item: (item.click_y, item.click_x, item.title))
        return ArticleViewportObservation(
            tuple(ordered),
            node_signature,
            _signature_has_loading(node_signature),
        )

    def _collect_text_nodes(
        self,
        root: Any,
        *,
        viewport: tuple[int, int, int, int],
    ) -> list[_TextNode]:
        queue: deque[tuple[Any, int]] = deque([(root, 0)])
        result: list[_TextNode] = []
        visited = 0
        while queue and visited < self.max_nodes:
            control, depth = queue.popleft()
            visited += 1
            if depth > 0:
                text = _control_text(control)
                rect = rect_to_tuple(_safe_get(control, "BoundingRectangle", None))
                is_offscreen = bool(_safe_get(control, "IsOffscreen", False))
                if text and not is_offscreen and _rect_intersects(rect, viewport):
                    result.append(
                        _TextNode(
                            text=text,
                            rect=rect,
                            hwnd=_safe_int(_safe_get(control, "NativeWindowHandle", 0)),
                            automation_id=str(_safe_get(control, "AutomationId", "") or ""),
                            control=control,
                        )
                    )
            if depth >= self.max_depth:
                continue
            try:
                children = control.GetChildren()
            except Exception:
                children = []
            for child in children or []:
                queue.append((child, depth + 1))
        return result


def is_article_title_text(text: str) -> bool:
    value = normalize_window_text(text)
    if not 2 <= len(value) <= 120:
        return False
    if value.lower() in EXCLUDED_TEXT or value in EXCLUDED_TEXT:
        return False
    if value.startswith("视频号") or value.startswith("贴图"):
        return False
    if _is_date_text(value) or _is_metric_text(value):
        return False
    if re.fullmatch(r"[\d.]+(?:万)?\+?", value):
        return False
    if re.search(r"\d+\s*篇原创", value) or re.search(r"\d+\s*个朋友关注", value):
        return False
    return True


def normalize_window_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or ""))
    value = value.replace("\u200b", "").replace("\ufeff", "").strip()
    return re.sub(r"\s+", " ", value)


def _build_fingerprint(title: str, automation_id: str) -> str:
    stable_source = f"{normalize_window_text(title)}\n{automation_id.strip()}"
    return hashlib.sha256(stable_source.encode("utf-8")).hexdigest()[:16]


def _metric_belongs_to_title(
    title_rect: tuple[int, int, int, int],
    metric_rect: tuple[int, int, int, int],
) -> bool:
    left, _top, right, bottom = title_rect
    metric_left, metric_top, metric_right, _metric_bottom = metric_rect
    vertical_gap = metric_top - bottom
    horizontal_overlap = max(left, metric_left) < min(right, metric_right)
    return 0 <= vertical_gap <= 140 and horizontal_overlap


def _metric_only_article_targets(
    nodes: list[_TextNode],
    metrics: list[_TextNode],
    *,
    matched_metric_rects: set[tuple[int, int, int, int]],
    seen: set[tuple[str, tuple[int, int, int, int]]],
    account_name: str,
    home_window: WindowInfo,
) -> list[ArticleTarget]:
    """兼容图片类卡片：有阅读/赞指标，但标题文本只暴露为点号或空白。"""
    result: list[ArticleTarget] = []
    ordered_nodes = sorted(nodes, key=lambda item: (item.rect[1], item.rect[0], item.text))
    for metric in sorted(metrics, key=lambda item: (item.rect[1], item.rect[0])):
        if metric.rect in matched_metric_rects:
            continue
        date_node = _nearest_card_date_node(ordered_nodes, metric)
        if date_node is None:
            continue
        title = _metric_only_article_title(date_node.text, metric.text)
        key = (normalize_window_text(title), metric.rect)
        if key in seen:
            continue
        seen.add(key)
        click_x, click_y = _rect_center(metric.rect)
        result.append(
            ArticleTarget(
                account_name=account_name,
                title=title,
                click_x=click_x,
                click_y=click_y,
                home_window_handle=home_window.handle,
                fingerprint=_build_fingerprint(title, f"metric-only:{metric.rect}"),
                control=metric.control,
            )
        )
    return result


def _nearest_card_date_node(nodes: list[_TextNode], metric: _TextNode) -> _TextNode | None:
    candidates = [
        node
        for node in nodes
        if (_is_date_text(node.text) or re.fullmatch(r"星期[一二三四五六日天]", node.text))
        and node.rect[3] <= metric.rect[1]
        and 0 <= metric.rect[1] - node.rect[3] <= 260
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.rect[1])


def _metric_only_article_title(date_text: str, metric_text: str) -> str:
    date_value = normalize_window_text(date_text)
    metric_value = normalize_window_text(metric_text)
    return f"图片文章（{date_value} {metric_value}）".strip()


def _is_date_text(value: str) -> bool:
    return value in {"今天", "昨天"} or bool(
        re.fullmatch(r"(?:\d{4}年)?\d{1,2}月\d{1,2}日", value)
    )


def _is_metric_text(value: str) -> bool:
    return bool(re.search(r"^阅读\s*[\d.]+(?:万)?\+?(?:.*赞\s*\d+)?", value))


def _node_visible_signature(nodes: list[_TextNode]) -> tuple[str, ...]:
    ordered = sorted(nodes, key=lambda item: (item.rect[1], item.rect[0], item.text))
    return tuple(
        normalized
        for node in ordered
        if (normalized := normalize_window_text(node.text))
    )


def _get_visible_ranges(document: Any) -> list[Any]:
    try:
        return list(document.GetTextPattern().GetVisibleRanges() or [])
    except Exception:
        return []


def _visible_range_signature(visible_ranges: list[Any]) -> tuple[str, ...]:
    result: list[str] = []
    for text_range in visible_ranges:
        try:
            result.extend(document_text_lines(str(text_range.GetText(-1) or "")))
        except Exception:
            continue
    return tuple(result)


def _signature_has_loading(signature: tuple[str, ...]) -> bool:
    return any(
        normalize_window_text(item).startswith(("正在加载", "加载中"))
        for item in signature
    )


def _visible_range_targets(
    document: Any,
    *,
    account_name: str,
    home_window: WindowInfo,
    visible_ranges: list[Any] | None = None,
) -> list[ArticleTarget]:
    """从 GetVisibleRanges 同时读取可见标题和坐标，不与全量文本错位。"""
    document_rect = rect_to_tuple(_safe_get(document, "BoundingRectangle", None))
    if not _valid_rect(document_rect):
        return []
    ranges = _get_visible_ranges(document) if visible_ranges is None else visible_ranges
    content_top = _visible_article_content_top(ranges, document_rect)
    result: list[ArticleTarget] = []
    occurrence_by_title: dict[str, int] = {}
    pending_text: list[str] = []
    pending_rectangles: list[tuple[int, int, int, int]] = []
    inside_article_group = False
    current_date_text = ""
    current_date_rect: tuple[int, int, int, int] | None = None

    def flush(
        *,
        metric_confirmed: bool,
        metric_text: str = "",
        metric_rectangles: list[tuple[int, int, int, int]] | None = None,
    ) -> None:
        nonlocal current_date_text, current_date_rect
        metric_rectangles = metric_rectangles or []
        if not pending_text and not (
            metric_confirmed and current_date_text and metric_rectangles
        ):
            return
        title = "".join(pending_text).strip()
        if (
            not metric_confirmed
            or not is_article_title_text(title)
            or not pending_rectangles
        ):
            if metric_confirmed and current_date_text and metric_rectangles:
                metric_rect = max(
                    metric_rectangles,
                    key=lambda item: ((item[2] - item[0]), -(item[1])),
                )
                fallback_title = _metric_only_article_title(
                    current_date_text,
                    metric_text,
                )
                normalized = normalize_window_text(fallback_title)
                occurrence = occurrence_by_title.get(normalized, 0) + 1
                occurrence_by_title[normalized] = occurrence
                result.append(
                    ArticleTarget(
                        account_name=account_name,
                        title=fallback_title,
                        click_x=_rect_center(metric_rect)[0],
                        click_y=_rect_center(metric_rect)[1],
                        home_window_handle=home_window.handle,
                        fingerprint=_build_fingerprint(
                            fallback_title,
                            f"visible-range-metric-only:{occurrence}",
                        ),
                        control=None,
                    )
                )
            pending_text.clear()
            pending_rectangles.clear()
            return
        metric_rect = max(
            metric_rectangles,
            key=lambda item: ((item[2] - item[0]), -(item[1])),
        )
        normalized = normalize_window_text(title)
        occurrence = occurrence_by_title.get(normalized, 0) + 1
        occurrence_by_title[normalized] = occurrence
        result.append(
            ArticleTarget(
                account_name=account_name,
                title=title,
                click_x=_rect_center(metric_rect)[0],
                click_y=_rect_center(metric_rect)[1],
                home_window_handle=home_window.handle,
                fingerprint=_build_fingerprint(
                    title,
                    f"visible-range:{occurrence}",
                ),
                control=None,
            )
        )
        pending_text.clear()
        pending_rectangles.clear()

    for text_range in ranges:
        try:
            range_text = str(text_range.GetText(-1) or "")
            raw_rectangles = text_range.GetBoundingRectangles()
        except Exception:
            continue
        rectangles = [
            rect_to_tuple(value)
            for value in raw_rectangles or []
            if _rect_intersects(rect_to_tuple(value), document_rect)
        ]
        for line in document_text_lines(range_text):
            if _is_date_text(line) or re.fullmatch(r"星期[一二三四五六日天]", line):
                # 没看到上一张卡片的指标，说明其标题可能只露出了一部分，不能点击。
                flush(metric_confirmed=False)
                # Chromium 可能把被固定导航栏遮住的首张卡片仍报告为可见；
                # 日期必须位于导航栏下方，才允许开始收集这张文章卡片。
                inside_article_group = any(rect[1] >= content_top for rect in rectangles)
                if inside_article_group:
                    current_date_text = line
                    current_date_rect = max(
                        (rect for rect in rectangles if rect[1] >= content_top),
                        key=lambda item: ((item[2] - item[0]), -(item[1])),
                        default=None,
                    )
                else:
                    current_date_text = ""
                    current_date_rect = None
                continue
            if not inside_article_group:
                continue
            if _is_metric_text(line):
                flush(
                    metric_confirmed=True,
                    metric_text=line,
                    metric_rectangles=[
                        rect for rect in rectangles if rect[1] >= content_top
                    ],
                )
                continue
            if line in {"正在加载...", "加载更多", "置顶"}:
                flush(metric_confirmed=False)
                continue
            pending_text.append(line)
            pending_rectangles.extend(
                rect for rect in rectangles if rect[1] >= content_top
            )
    # 视口末尾没有“阅读/赞”指标的标题通常是被窗口底部裁切的半张卡片。
    flush(metric_confirmed=False)
    return result


def _visible_article_content_top(
    visible_ranges: list[Any],
    document_rect: tuple[int, int, int, int],
) -> int:
    """返回固定“全部/文章/视频号”导航栏下沿，避免点击其后被遮挡的卡片。"""
    document_top = document_rect[1]
    header_zone_bottom = document_top + min(
        240,
        max(80, (document_rect[3] - document_top) // 4),
    )
    navigation_bottoms: list[int] = []
    for text_range in visible_ranges:
        try:
            lines = document_text_lines(str(text_range.GetText(-1) or ""))
            rectangles = [
                rect_to_tuple(value)
                for value in text_range.GetBoundingRectangles() or []
            ]
        except Exception:
            continue
        if not any(line in {"全部", "文章", "视频号"} for line in lines):
            continue
        navigation_bottoms.extend(
            rect[3]
            for rect in rectangles
            if _rect_intersects(rect, document_rect) and rect[1] < header_zone_bottom
        )
    return max(navigation_bottoms, default=document_top)


def _rect_intersects(
    rect: tuple[int, int, int, int],
    viewport: tuple[int, int, int, int],
) -> bool:
    return (
        _valid_rect(rect)
        and rect[2] > viewport[0]
        and rect[0] < viewport[2]
        and rect[3] > viewport[1]
        and rect[1] < viewport[3]
    )


def _rect_center(rect: tuple[int, int, int, int]) -> tuple[int, int]:
    return ((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)


def _control_text(control: Any) -> str:
    for name in ("Name", "Value"):
        value = normalize_window_text(str(_safe_get(control, name, "") or ""))
        if value:
            return value
    return ""


def _valid_rect(rect: tuple[int, int, int, int]) -> bool:
    return rect[2] > rect[0] and rect[3] > rect[1]


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
