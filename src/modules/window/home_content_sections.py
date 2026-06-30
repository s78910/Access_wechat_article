from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


HOME_NAV_LABELS = {"全部", "贴图", "文章", "视频号"}
HOME_SECTION_LABELS = {"贴图", "文章", "视频号"}
HOME_EXCLUDED_SECTION_LABELS = {"贴图", "视频号"}
HOME_NAV_ROW_TOLERANCE_PX = 40
HOME_SECTION_GAP_PX = 24


@dataclass(frozen=True)
class HomeContentSectionMarker:
    """主页内容区的分段标记。"""

    label: str
    rect: tuple[int, int, int, int]

    @property
    def top(self) -> int:
        return int(self.rect[1])


def filter_home_article_targets(
    targets: Sequence[Any],
    text_nodes: Sequence[tuple[str, tuple[int, int, int, int]]],
) -> list[Any]:
    """过滤掉主页头部以及贴图 / 视频号内容段中的非文章候选。"""
    nav_bottom = _detect_nav_row_bottom(text_nodes)
    if nav_bottom is None:
        return list(targets)
    markers = _build_home_content_section_markers(text_nodes, nav_bottom=nav_bottom)

    filtered: list[Any] = []
    for target in targets:
        rect = _target_rect(target)
        if not _valid_rect(rect):
            filtered.append(target)
            continue
        if _is_above_home_content_area(rect, nav_bottom):
            continue
        if _is_in_excluded_section(rect, markers):
            continue
        filtered.append(target)
    return filtered


def _build_home_content_section_markers(
    text_nodes: Sequence[tuple[str, tuple[int, int, int, int]]],
    *,
    nav_bottom: int,
) -> list[HomeContentSectionMarker]:
    markers: list[HomeContentSectionMarker] = []
    for text, rect in text_nodes:
        label = _normalize_text(text)
        if label not in HOME_SECTION_LABELS:
            continue
        if not _valid_rect(rect):
            continue
        if rect[1] < nav_bottom + HOME_SECTION_GAP_PX:
            continue
        markers.append(HomeContentSectionMarker(label=label, rect=rect))

    markers.sort(key=lambda marker: (marker.top, marker.rect[0], marker.rect[2]))
    return markers


def _detect_nav_row_bottom(text_nodes: Sequence[tuple[str, tuple[int, int, int, int]]]) -> int | None:
    nav_rects: list[tuple[int, int, int, int]] = []
    for text, rect in text_nodes:
        label = _normalize_text(text)
        if label in HOME_NAV_LABELS and _valid_rect(rect):
            nav_rects.append(rect)
    if not nav_rects:
        return None

    nav_top = min(rect[1] for rect in nav_rects)
    nav_row_rects = [rect for rect in nav_rects if rect[1] <= nav_top + HOME_NAV_ROW_TOLERANCE_PX]
    if not nav_row_rects:
        nav_row_rects = nav_rects
    return max(rect[3] for rect in nav_row_rects)


def _is_in_excluded_section(
    rect: tuple[int, int, int, int],
    markers: Sequence[HomeContentSectionMarker],
) -> bool:
    candidate_top = int(rect[1])
    current_marker: HomeContentSectionMarker | None = None
    for marker in markers:
        if marker.top > candidate_top:
            break
        current_marker = marker
    return current_marker is not None and current_marker.label in HOME_EXCLUDED_SECTION_LABELS


def _is_above_home_content_area(rect: tuple[int, int, int, int], nav_bottom: int) -> bool:
    """导航栏上方是账号资料区，不把其中的公众号名当作文章标题。"""
    return int(rect[1]) < int(nav_bottom)


def _target_rect(target: Any) -> tuple[int, int, int, int]:
    rect = getattr(target, "rect", None)
    if isinstance(rect, (list, tuple)) and len(rect) == 4:
        return tuple(int(item) for item in rect)
    return (0, 0, 0, 0)


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _valid_rect(rect: tuple[int, int, int, int]) -> bool:
    left, top, right, bottom = rect
    return right > left and bottom > top and (right - left) >= 20 and (bottom - top) >= 10
