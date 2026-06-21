from __future__ import annotations

import re
from datetime import datetime
from typing import Any


def now_text() -> str:
    """返回 SQLite 和 JSON 常用的当前时间字符串。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_datetime_text(value: Any) -> str:
    """把常见时间文本统一成 YYYY-MM-DD HH:MM:SS。"""
    text = str(value or "").strip().replace("T", " ")
    if not text:
        return now_text()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", text):
        return f"{text}:00"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}.*", text):
        return text[:19]
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}) (\d{2})-(\d{2})", text)
    if match:
        return f"{match.group(1)} {match.group(2)}:{match.group(3)}:00"
    return text


def normalize_minute_time_text(value: Any) -> str:
    """把文章发布时间统一成分钟级 YYYY-MM-DD HH:MM。"""
    normalized = normalize_datetime_text(value)
    return normalized[:16] if len(normalized) >= 16 else normalized


def format_datetime_for_dir(value: Any) -> str:
    """把时间转成目录名可用格式，例如 2026-06-20 14-30。"""
    minute_text = normalize_minute_time_text(value)
    return minute_text.replace(":", "-")
