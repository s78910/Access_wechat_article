from __future__ import annotations

import html
import re
from typing import Any


ACCOUNT_NAME_PLACEHOLDER_MARKERS = (
    "等待识别",
    "未检测到",
    "检测到微信窗口",
    "已检测到公众号窗口",
    "无法读取主页内容",
    "主页窗口读取失败",
)


def normalize_account_name_text(value: Any) -> str:
    """统一清洗公众号名文本，避免各模块对转义和空白处理不一致。"""
    return (
        html.unescape(str(value or ""))
        .replace("\\/", "/")
        .replace("\\x26", "&")
        .replace("\\u0026", "&")
        .strip()
    )


def is_valid_account_name_text(value: Any) -> bool:
    """判断文本是否像真实公众号名，过滤 HTML 属性名和窗口状态提示。"""
    text = normalize_account_name_text(value)
    if not text:
        return False
    if any(marker in text for marker in ACCOUNT_NAME_PLACEHOLDER_MARKERS):
        return False

    lowered = text.lower()
    invalid_values = {
        "未知公众号",
        "未识别公众号",
        "未识别到主页公众号名称",
        "data-miniprogram-nickname",
        "miniprogram-nickname",
        "nickname",
        "author",
        "undefined",
        "null",
    }
    if lowered in invalid_values:
        return False
    if lowered.startswith("data-"):
        return False
    if re.fullmatch(r"[a-z0-9_-]+", lowered) and "nickname" in lowered:
        return False
    return True


def first_valid_account_name(*values: Any, default: str = "未知公众号") -> str:
    """返回第一个可信公众号名；所有入库和归档路径都应复用这层判断。"""
    for value in values:
        text = normalize_account_name_text(value)
        if is_valid_account_name_text(text):
            return text
    return default
