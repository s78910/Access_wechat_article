from __future__ import annotations

import html
import re
from typing import Any


def normalize_text(value: Any) -> str:
    """去掉首尾空白，并处理网页文本里常见的转义字符。"""
    return (
        html.unescape(str(value or ""))
        .replace("\\/", "/")
        .replace("\\x26", "&")
        .replace("\\u0026", "&")
        .strip()
    )


def collapse_spaces(value: Any) -> str:
    """把连续空白合并成一个空格。"""
    return re.sub(r"\s+", " ", normalize_text(value))
