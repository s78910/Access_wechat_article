from __future__ import annotations

from collections import deque
from collections.abc import Callable
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
from src.modules.window.article_date_filter import normalize_home_date_text
from src.modules.window.uia_article_group_parser import (
    UiaArticleGroupParser,
    UiaArticleTreeObservation,
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

ARTICLE_NAVIGATION_TEXT = frozenset({"全部", "贴图", "文章", "视频号"})


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
    range_count: int = 0
    decisions: tuple[dict[str, Any], ...] = ()


class UiaArticleCardReader:
    """从公众号主页 UIA 树读取当前可见文章卡片，不执行点击。"""

    def __init__(self, *, max_depth: int = 12, max_nodes: int = 5000) -> None:
        self.max_depth = max(1, int(max_depth))
        self.max_nodes = max(1, int(max_nodes))
        self._group_parser = UiaArticleGroupParser(
            max_depth=self.max_depth,
            max_nodes=self.max_nodes,
        )

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

        # 单篇边界只由 UIA 控件树中的“日期组 -> 文章卡片”父子关系确定。
        # TextPattern 仍用于页面文本签名和懒加载检测，不参与树路径的文章划分。
        document = find_wechat_document_control(home_window.control)
        visible_ranges: list[Any] = []
        text_pattern_decisions: list[dict[str, Any]] = []
        if document is not None:
            visible_ranges = _get_visible_ranges(document)
            text_signature = _visible_range_signature(visible_ranges)
            loading = _signature_has_loading(text_signature)
            document_rect = rect_to_tuple(
                _safe_get(document, "BoundingRectangle", None)
            )
            viewport_rect = _rect_intersection(document_rect, home_window.rect)
            if _valid_rect(viewport_rect):
                content_top = _visible_article_content_top(
                    document,
                    visible_ranges,
                    viewport_rect,
                )
                tree_observation = self._group_parser.parse(
                    document,
                    viewport=viewport_rect,
                    content_top=content_top,
                )
                if tree_observation.group_count > 0:
                    tree_targets = _tree_article_targets(
                        tree_observation,
                        account_name=account_name,
                        home_window=home_window,
                    )
                    tree_signature = _tree_visible_signature(tree_observation)
                    return ArticleViewportObservation(
                        tuple(tree_targets),
                        tree_signature or text_signature,
                        loading,
                        len(visible_ranges),
                        tree_observation.decisions,
                    )

            # 兼容暂时没有暴露稳定日期组结构的页面；只有控件树完全无法形成
            # 日期组时才允许 TextPattern 兜底，避免混合范围覆盖可信的树结果。
            if visible_ranges:
                targets = _visible_range_targets(
                    document,
                    account_name=account_name,
                    home_window=home_window,
                    visible_ranges=visible_ranges,
                    decision_sink=text_pattern_decisions.append,
                )
                if targets:
                    return ArticleViewportObservation(
                        tuple(targets),
                        text_signature,
                        loading,
                        len(visible_ranges),
                        tuple(text_pattern_decisions),
                    )
                if loading:
                    return ArticleViewportObservation(
                        (),
                        text_signature,
                        True,
                        len(visible_ranges),
                        tuple(text_pattern_decisions),
                    )

        # 没有 Document 日期组且 TextPattern 也无结果时，保留旧节点读取兜底。
        nodes = self._collect_text_nodes(
            home_window.control,
            viewport=home_window.rect,
        )
        node_signature = _node_visible_signature(nodes)

        metrics = [node for node in nodes if _is_metric_text(node.text)]
        # 文章主页卡片应带有“阅读…赞…”指标锚点。没有锚点时通常是文章详情页或
        # Chromium 工具栏；禁止退化为“所有可读文本都是文章”的宽松模式。
        if not metrics:
            if document is None:
                return ArticleViewportObservation(
                    (),
                    node_signature,
                    _signature_has_loading(node_signature),
                    len(visible_ranges),
                    tuple(text_pattern_decisions),
                )
            return ArticleViewportObservation(
                (),
                node_signature,
                _signature_has_loading(node_signature),
                len(visible_ranges),
                tuple(text_pattern_decisions),
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
            matched_date = _nearest_card_date_node(nodes, matched_metric)
            if matched_date is None:
                continue
            click_x, click_y = _rect_center(matched_metric.rect)
            published_date = normalize_home_date_text(matched_date.text)
            targets.append(
                ArticleTarget(
                    account_name=account_name,
                    title=display_article_title(node.text),
                    click_x=click_x,
                    click_y=click_y,
                    home_window_handle=node.hwnd or home_window.handle,
                    fingerprint=_build_fingerprint(node.text, node.automation_id),
                    control=matched_metric.control,
                    date_text=matched_date.text,
                    published_date=published_date.isoformat() if published_date else "",
                    date_rect=matched_date.rect,
                    title_rect=node.rect,
                    metric_text=matched_metric.text,
                    metric_rect=matched_metric.rect,
                    raw_title=node.text.strip(),
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
            len(visible_ranges),
            tuple(text_pattern_decisions),
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


def _tree_article_targets(
    observation: UiaArticleTreeObservation,
    *,
    account_name: str,
    home_window: WindowInfo,
) -> list[ArticleTarget]:
    result: list[ArticleTarget] = []
    for card in observation.cards:
        raw_title = normalize_window_text(card.raw_title)
        title = display_article_title(raw_title)
        published_date = normalize_home_date_text(card.date_text)
        click_x, click_y = _rect_center(card.metric_rect)
        result.append(
            ArticleTarget(
                account_name=account_name,
                title=title,
                click_x=click_x,
                click_y=click_y,
                home_window_handle=home_window.handle,
                fingerprint=_build_fingerprint(
                    raw_title or title,
                    (
                        "uia-tree:"
                        f"{card.date_text}:"
                        f"{card.metric_automation_id}"
                    ),
                ),
                control=card.metric_control,
                date_text=card.date_text,
                published_date=(
                    published_date.isoformat() if published_date else ""
                ),
                date_rect=card.date_rect,
                title_rect=card.title_rect,
                metric_text=card.metric_text,
                metric_rect=card.metric_rect,
                raw_title=raw_title,
            )
        )
    return result


def _tree_visible_signature(
    observation: UiaArticleTreeObservation,
) -> tuple[str, ...]:
    return tuple(
        "\n".join(
            (
                card.date_text,
                card.raw_title,
                card.metric_text,
            )
        )
        for card in observation.cards
    )


def is_article_title_text(text: str) -> bool:
    value = normalize_window_text(text)
    if not value or len(value) > 120:
        return False
    if value.lower() in EXCLUDED_TEXT or value in EXCLUDED_TEXT:
        return False
    if value.startswith("视频号") or value.startswith("贴图"):
        return False
    if _is_date_text(value) or _is_metric_text(value):
        return False
    if re.fullmatch(r"(?=.*\d)[\d.]+(?:万)?\+?", value):
        return False
    if re.search(r"\d+\s*篇原创", value) or re.search(r"\d+\s*个朋友关注", value):
        return False
    return True


def display_article_title(text: str) -> str:
    """符号类弱标题保留为候选，但向单篇任务提供稳定的占位标题。"""

    value = normalize_window_text(text)
    if not value or not any(character.isalnum() for character in value):
        return "xxx"
    return value


def merge_article_targets(
    primary: list[ArticleTarget],
    supplemental: list[ArticleTarget],
) -> list[ArticleTarget]:
    """合并 UIA 节点和文档范围结果，保留各自可确认的阅读坐标。"""

    result = list(primary)
    seen = {_target_metric_key(item) for item in primary}
    for item in supplemental:
        key = _target_metric_key(item)
        if key in seen:
            continue
        result.append(item)
        seen.add(key)
    return sorted(result, key=lambda item: (item.click_y, item.click_x, item.title))


def _target_metric_key(target: ArticleTarget) -> tuple[Any, ...]:
    """用指标节点的位置去重，不把日期或标题变化误当成新文章。"""

    if target.metric_rect is not None and _valid_rect(target.metric_rect):
        return ("rect", target.metric_rect)
    return (
        "point",
        target.click_x,
        target.click_y,
        normalize_window_text(target.metric_text),
    )


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
        published_date = normalize_home_date_text(date_node.text)
        result.append(
            ArticleTarget(
                account_name=account_name,
                title=title,
                click_x=click_x,
                click_y=click_y,
                home_window_handle=home_window.handle,
                fingerprint=_build_fingerprint(title, f"metric-only:{metric.rect}"),
                control=metric.control,
                date_text=date_node.text,
                published_date=published_date.isoformat() if published_date else "",
                date_rect=date_node.rect,
                title_rect=None,
                metric_text=metric.text,
                metric_rect=metric.rect,
                raw_title="",
            )
        )
    return result


def _nearest_card_date_node(nodes: list[_TextNode], metric: _TextNode) -> _TextNode | None:
    candidates = [
        node
        for node in nodes
        if (_is_date_text(node.text) or re.fullmatch(r"星期[一二三四五六日天]", node.text))
        and node.rect[3] <= metric.rect[1]
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.rect[1])


def _metric_only_article_title(_date_text: str, _metric_text: str) -> str:
    return "xxx"


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
    inherited_date_text: str = "",
    decision_sink: Callable[[dict[str, Any]], None] | None = None,
) -> list[ArticleTarget]:
    """按“阅读指标”边界解析可见文章，指标本身是唯一可点击锚点。"""
    document_rect = rect_to_tuple(_safe_get(document, "BoundingRectangle", None))
    if not _valid_rect(document_rect):
        return []
    viewport_rect = _rect_intersection(document_rect, home_window.rect)
    if not _valid_rect(viewport_rect):
        return []
    ranges = _get_visible_ranges(document) if visible_ranges is None else visible_ranges
    content_top = _visible_article_content_top(document, ranges, viewport_rect)
    navigation_range_index = _visible_article_navigation_index(ranges)
    result: list[ArticleTarget] = []
    pending_text: list[str] = []
    pending_rectangles: list[tuple[int, int, int, int]] = []
    current_date_text = normalize_window_text(inherited_date_text)
    current_date_rect: tuple[int, int, int, int] | None = None
    seen_metric_keys: set[tuple[Any, ...]] = set()
    occurrence_by_title: dict[str, int] = {}
    article_boundary_confirmed = False

    def report_decision(
        reason: str,
        *,
        title_fragment: str = "",
        metric_text: str = "",
        title_rect: tuple[int, int, int, int] | None = None,
        metric_rect: tuple[int, int, int, int] | None = None,
    ) -> None:
        if decision_sink is None:
            return
        decision_sink(
            {
                "status": "discarded",
                "reason": reason,
                "titleFragment": title_fragment,
                "dateText": current_date_text,
                "metricText": metric_text,
                "titleRect": title_rect,
                "metricRect": metric_rect,
            }
        )

    def clear_pending() -> None:
        pending_text.clear()
        pending_rectangles.clear()

    def flush_metric(
        metric_text: str,
        metric_rectangles: list[tuple[int, int, int, int]],
    ) -> None:
        nonlocal article_boundary_confirmed
        if not metric_rectangles:
            # 无坐标指标是上一张文章的结束边界，只能为后续文章建立起点。
            clear_pending()
            article_boundary_confirmed = True
            return
        metric_rect = max(
            metric_rectangles,
            key=lambda item: ((item[2] - item[0]), -(item[1])),
        )
        metric_key = ("rect", metric_rect)
        if metric_key in seen_metric_keys:
            clear_pending()
            article_boundary_confirmed = True
            return

        seen_metric_keys.add(metric_key)
        title = _clean_article_title(pending_text)
        title_rect = _merge_rectangles(pending_rectangles)
        clear_pending()
        if not article_boundary_confirmed:
            # 继承日期时，视口顶部可能只是上一张卡片的标题后半段。
            # 未先观察到日期或前一阅读指标，不能把该残片作为新文章。
            report_decision(
                "未检测到日期或前一阅读指标边界",
                title_fragment=title,
                metric_text=metric_text,
                title_rect=title_rect,
                metric_rect=metric_rect,
            )
            article_boundary_confirmed = True
            return
        article_boundary_confirmed = True
        if title_rect is not None and title_rect == metric_rect:
            # TextPattern 滚动过渡帧可能给标题和阅读指标返回同一块范围；
            # 此时标题边界不可信，不能生成文章记录。
            report_decision(
                "标题与阅读指标坐标重合，页面可能仍在滚动",
                title_fragment=title,
                metric_text=metric_text,
                title_rect=title_rect,
                metric_rect=metric_rect,
            )
            return
        # 只有指标有坐标且区间中存在正文文本时才生成文章。
        # 空区间不再自动生成 xxx，避免重复节点或孤立指标制造假文章。
        if not title or not is_article_title_text(title):
            report_decision(
                "阅读指标前没有可用标题",
                title_fragment=title,
                metric_text=metric_text,
                title_rect=title_rect,
                metric_rect=metric_rect,
            )
            return

        display_title = display_article_title(title)
        normalized = normalize_window_text(display_title)
        occurrence = occurrence_by_title.get(normalized, 0) + 1
        occurrence_by_title[normalized] = occurrence
        published_date = normalize_home_date_text(current_date_text)
        result.append(
            ArticleTarget(
                account_name=account_name,
                title=display_title,
                click_x=_rect_center(metric_rect)[0],
                click_y=_rect_center(metric_rect)[1],
                home_window_handle=home_window.handle,
                fingerprint=_build_fingerprint(
                    display_title,
                    f"visible-range:{occurrence}",
                ),
                control=None,
                date_text=current_date_text,
                published_date=published_date.isoformat() if published_date else "",
                date_rect=current_date_rect,
                title_rect=title_rect,
                metric_text=metric_text,
                metric_rect=metric_rect,
                raw_title=title,
            )
        )

    for range_index, text_range in enumerate(ranges):
        try:
            range_text = str(text_range.GetText(-1) or "")
            raw_rectangles = text_range.GetBoundingRectangles()
        except Exception:
            continue
        valid_rectangles = [
            rect
            for value in raw_rectangles or []
            if _valid_rect(rect := rect_to_tuple(value))
        ]
        rectangles = [
            rect
            for rect in valid_rectangles
            if _rect_fully_inside(rect, viewport_rect)
        ]
        if range_index <= navigation_range_index:
            continue
        content_rectangles = [
            rect for rect in rectangles if rect[3] > content_top
        ]
        for line in document_text_lines(range_text):
            if _is_date_text(line) or re.fullmatch(r"星期[一二三四五六日天]", line):
                # 日期可能被固定导航栏遮住，但其后的标题和阅读指标仍完整可见；
                # 它只是当前文章的日期上下文，不负责切分文章区间。
                clear_pending()
                current_date_text = line
                current_date_rect = max(
                    rectangles,
                    key=lambda item: ((item[2] - item[0]), -(item[1])),
                    default=None,
                )
                article_boundary_confirmed = True
                continue
            if _is_metric_text(line):
                metric_source_rectangles = [
                    rect
                    for rect in valid_rectangles
                    if rect[1] >= content_top
                ]
                metric_rectangles = [
                    rect
                    for rect in metric_source_rectangles
                    if _rect_fully_inside(rect, viewport_rect)
                ]
                if len(metric_rectangles) != len(metric_source_rectangles):
                    metric_rectangles = []
                metric_key = (
                    "rect",
                    metric_rectangles[0],
                ) if metric_rectangles else ("text", normalize_window_text(line))
                if metric_key in seen_metric_keys:
                    # Chromium/UIA 偶尔重复报告同一阅读节点；不再次清空或生成目标。
                    continue
                if not metric_rectangles:
                    # 这是当前可视区域上方文章留下的边界，丢弃其前面的残缺文本。
                    report_decision(
                        "阅读指标没有完整位于主页可视区",
                        title_fragment=_clean_article_title(pending_text),
                        metric_text=line,
                        title_rect=_merge_rectangles(pending_rectangles),
                        metric_rect=max(
                            metric_source_rectangles,
                            key=lambda item: ((item[2] - item[0]), -(item[1])),
                            default=None,
                        ),
                    )
                    seen_metric_keys.add(metric_key)
                    clear_pending()
                    article_boundary_confirmed = True
                    continue
                flush_metric(
                    line,
                    metric_rectangles,
                )
                continue
            if _is_article_control_text(line):
                # 展开/置顶等控件不属于标题；加载提示还意味着当前文本不完整。
                if line in {"正在加载...", "加载更多"}:
                    clear_pending()
                continue
            if not is_article_title_text(line):
                continue
            if rectangles and not content_rectangles:
                # 公众号名称、关注按钮等主页头部文本位于分类导航上方。
                continue
            if not valid_rectangles and not pending_text and not current_date_text:
                # 没有坐标且还未进入日期/文章区间的文本不能确认属于文章卡片。
                continue
            recovered_title = _recover_enclosing_title(text_range, line)
            _append_title_fragment(pending_text, recovered_title)
            pending_rectangles.extend(content_rectangles)
    # 视口末尾没有有坐标指标的区间是被裁切的半张卡片，不生成候选。
    trailing_title = _clean_article_title(pending_text)
    if trailing_title:
        report_decision(
            "视口末尾标题没有对应的完整阅读指标",
            title_fragment=trailing_title,
            title_rect=_merge_rectangles(pending_rectangles),
        )
    clear_pending()
    return result


def _clean_article_title(lines: list[str]) -> str:
    """清理指标区间中的日期、控件和空白，只保留标题原文。"""

    cleaned = [
        normalize_window_text(line)
        for line in lines
        if normalize_window_text(line)
        and not _is_date_text(normalize_window_text(line))
        and not _is_metric_text(normalize_window_text(line))
        and not _is_article_control_text(line)
    ]
    # TextPattern 可能把同一标题按换行拆成多个范围，拼接时不额外插入空格。
    return normalize_window_text("".join(cleaned))


def _recover_enclosing_title(text_range: Any, visible_fragment: str) -> str:
    """可见范围被裁切时，优先读取所属 UIA 文本控件暴露的完整名称。"""

    visible = normalize_window_text(visible_fragment)
    try:
        enclosing_control = text_range.GetEnclosingControl()
        enclosing_name = str(_safe_get(enclosing_control, "Name", "") or "")
    except Exception:
        enclosing_name = ""
    candidate = _clean_article_title(document_text_lines(enclosing_name))
    if (
        candidate
        and len(candidate) > len(visible)
        and visible in candidate
        and is_article_title_text(candidate)
    ):
        return candidate
    return visible_fragment


def _append_title_fragment(pending_text: list[str], fragment: str) -> None:
    """合并标题片段；同一完整控件名被多个可见行返回时只保留一次。"""

    normalized = normalize_window_text(fragment)
    if not normalized:
        return
    current = _clean_article_title(pending_text)
    if current:
        if normalized == current or normalized in current:
            return
        if current in normalized:
            pending_text[:] = [normalized]
            return
    pending_text.append(normalized)


def _is_article_control_text(value: str) -> bool:
    normalized = normalize_window_text(value)
    return normalized in {
        "展开",
        "收起",
        "置顶",
        "加载更多",
        "正在加载...",
        "全部",
        "文章",
        "视频号",
    }


def _visible_article_content_top(
    document: Any,
    visible_ranges: list[Any],
    document_rect: tuple[int, int, int, int],
) -> int:
    """返回分类导航栏下沿，导航之后才是可以解析的文章区域。"""
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
        if not any(line in ARTICLE_NAVIGATION_TEXT for line in lines):
            continue
        navigation_bottoms.extend(
            rect[3]
            for rect in rectangles
            if _rect_intersects(rect, document_rect) and rect[1] < header_zone_bottom
        )
    navigation_bottoms.extend(
        _uia_navigation_bottoms(document, document_rect, header_zone_bottom)
    )
    return max(navigation_bottoms, default=document_top)


def _visible_article_navigation_index(visible_ranges: list[Any]) -> int:
    """返回最后一个分类导航文本范围的序号，用于排除其前面的主页头部。"""

    result = -1
    for index, text_range in enumerate(visible_ranges):
        try:
            lines = document_text_lines(str(text_range.GetText(-1) or ""))
        except Exception:
            continue
        if any(line in ARTICLE_NAVIGATION_TEXT for line in lines):
            result = index
    return result


def _uia_navigation_bottoms(
    document: Any,
    document_rect: tuple[int, int, int, int],
    header_zone_bottom: int,
) -> list[int]:
    """读取 UIA 分类链接的真实下沿，弥补 TextPattern 字形矩形偏小。"""

    queue: deque[tuple[Any, int]] = deque([(document, 0)])
    result: list[int] = []
    visited = 0
    while queue and visited < 500:
        control, depth = queue.popleft()
        visited += 1
        text = normalize_window_text(str(_safe_get(control, "Name", "") or ""))
        rect = rect_to_tuple(_safe_get(control, "BoundingRectangle", None))
        if (
            text in ARTICLE_NAVIGATION_TEXT
            and _rect_intersects(rect, document_rect)
            and rect[1] < header_zone_bottom
        ):
            result.append(rect[3])
        if depth >= 10:
            continue
        try:
            children = control.GetChildren()
        except Exception:
            children = []
        queue.extend((child, depth + 1) for child in children or [])
    return result


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


def _rect_fully_inside(
    rect: tuple[int, int, int, int],
    viewport: tuple[int, int, int, int],
) -> bool:
    return (
        _valid_rect(rect)
        and rect[0] >= viewport[0]
        and rect[1] >= viewport[1]
        and rect[2] <= viewport[2]
        and rect[3] <= viewport[3]
    )


def _rect_intersection(
    left: tuple[int, int, int, int],
    right: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    return (
        max(left[0], right[0]),
        max(left[1], right[1]),
        min(left[2], right[2]),
        min(left[3], right[3]),
    )


def _rect_center(rect: tuple[int, int, int, int]) -> tuple[int, int]:
    return ((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)


def _merge_rectangles(
    rectangles: list[tuple[int, int, int, int]],
) -> tuple[int, int, int, int] | None:
    valid = [rect for rect in rectangles if _valid_rect(rect)]
    if not valid:
        return None
    return (
        min(rect[0] for rect in valid),
        min(rect[1] for rect in valid),
        max(rect[2] for rect in valid),
        max(rect[3] for rect in valid),
    )


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
