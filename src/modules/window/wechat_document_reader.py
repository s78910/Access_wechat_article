from __future__ import annotations

from collections import deque
import re
from typing import Any

from src.modules.window.wechat_home_window_finder import rect_to_tuple


DOCUMENT_CONTROL_TYPE = "documentcontrol"
OBJECT_REPLACEMENT_CHARACTER = "\ufffc"


def find_wechat_document_control(root: Any, *, max_depth: int = 14) -> Any | None:
    if root is None:
        return None
    queue: deque[tuple[Any, int]] = deque([(root, 0)])
    while queue:
        control, depth = queue.popleft()
        control_type = str(_safe_get(control, "ControlTypeName", "") or "").lower()
        if control_type == DOCUMENT_CONTROL_TYPE:
            return control
        if depth >= max_depth:
            continue
        try:
            children = control.GetChildren()
        except Exception:
            children = []
        queue.extend((child, depth + 1) for child in children or [])
    return None


def read_wechat_document_text(root: Any) -> tuple[Any | None, str]:
    document = find_wechat_document_control(root)
    if document is None:
        return None, ""
    try:
        text = document.GetTextPattern().DocumentRange.GetText(-1)
    except Exception:
        text = ""
    return document, str(text or "")


def document_text_lines(text: str) -> list[str]:
    result: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.replace(OBJECT_REPLACEMENT_CHARACTER, "")
        line = re.sub(r"[\u2000-\u200a\u202f\u205f\u3000]+", " ", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            result.append(line)
    return result


def document_bounding_rectangles(document: Any) -> list[tuple[int, int, int, int]]:
    try:
        raw_rectangles = document.GetTextPattern().DocumentRange.GetBoundingRectangles()
    except Exception:
        return []
    result: list[tuple[int, int, int, int]] = []
    for value in raw_rectangles or []:
        rect = rect_to_tuple(value)
        if rect[2] > rect[0] and rect[3] > rect[1]:
            result.append(rect)
    return result


def _safe_get(value: Any, name: str, default: Any) -> Any:
    try:
        return getattr(value, name)
    except Exception:
        return default
