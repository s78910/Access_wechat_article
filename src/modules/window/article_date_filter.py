from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
import re


class DateFilterDecision(str, Enum):
    """主页按日期倒序遍历时，对当前文章采取的动作。"""

    INCLUDE = "include"
    SKIP = "skip"
    STOP = "stop"


@dataclass(frozen=True, slots=True)
class ArticleDateFilter:
    """将前端日期条件转换为可复用的倒序主页筛选规则。"""

    mode: str
    start_date: date | None = None
    end_date: date | None = None

    @classmethod
    def create(
        cls,
        *,
        mode: str = "all",
        start_date: str | date | None = None,
        end_date: str | date | None = None,
    ) -> ArticleDateFilter:
        normalized_mode = str(mode or "all").strip().lower()
        if normalized_mode not in {"all", "range", "before", "after"}:
            raise ValueError(f"不支持的主页日期筛选方式：{mode}")
        parsed_start = _parse_iso_date(start_date)
        parsed_end = _parse_iso_date(end_date)
        if normalized_mode in {"range", "after"} and parsed_start is None:
            raise ValueError("当前日期筛选方式必须填写起始日期")
        if normalized_mode in {"range", "before"} and parsed_end is None:
            raise ValueError("当前日期筛选方式必须填写截止日期")
        if parsed_start is not None and parsed_end is not None and parsed_start > parsed_end:
            raise ValueError("起始日期不能晚于截止日期")
        return cls(normalized_mode, parsed_start, parsed_end)

    def decide(self, article_date: date | None) -> DateFilterDecision:
        # 没有归属日期的卡片不能参与日期筛选，也不能安全分发给单篇任务。
        if article_date is None:
            return DateFilterDecision.SKIP
        if self.mode == "all":
            return DateFilterDecision.INCLUDE
        if self.mode == "range":
            assert self.start_date is not None and self.end_date is not None
            if article_date > self.end_date:
                return DateFilterDecision.SKIP
            if article_date < self.start_date:
                return DateFilterDecision.STOP
            return DateFilterDecision.INCLUDE
        if self.mode == "before":
            assert self.end_date is not None
            return (
                DateFilterDecision.INCLUDE
                if article_date >= self.end_date
                else DateFilterDecision.STOP
            )
        assert self.start_date is not None
        return (
            DateFilterDecision.SKIP
            if article_date > self.start_date
            else DateFilterDecision.INCLUDE
        )

    @property
    def label(self) -> str:
        if self.mode == "range":
            return f"日期范围：{self.start_date} 至 {self.end_date}（含边界）"
        if self.mode == "before":
            return f"截止日期：从当前位置至 {self.end_date}（含当天）"
        if self.mode == "after":
            return f"起始日期：从 {self.start_date} 或之前最近日期开始"
        return "不限日期"


def normalize_home_date_text(value: str, *, today: date | None = None) -> date | None:
    """把微信主页的相对日期文本转换成可比较的自然日。"""

    text = str(value or "").strip()
    current = today or date.today()
    if text == "今天":
        return current
    if text == "昨天":
        return current - timedelta(days=1)
    weekday_match = re.fullmatch(r"星期([一二三四五六日天])", text)
    if weekday_match:
        target_weekday = "一二三四五六日".index(
            "日" if weekday_match.group(1) == "天" else weekday_match.group(1)
        )
        days_back = (current.weekday() - target_weekday) % 7
        return current - timedelta(days=days_back)
    absolute_match = re.fullmatch(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日", text)
    if not absolute_match:
        return None
    explicit_year, month_text, day_text = absolute_match.groups()
    month = int(month_text)
    day = int(day_text)
    if explicit_year:
        return _safe_date(int(explicit_year), month, day)
    candidate = _safe_date(current.year, month, day)
    if candidate is not None and candidate > current:
        candidate = _safe_date(current.year - 1, month, day)
    return candidate


def parse_target_published_date(value: object) -> date | None:
    """优先读取目标中的标准日期，兼容仅有主页日期原文的旧目标。"""

    published = str(getattr(value, "published_date", "") or "").strip()
    if published:
        return _parse_iso_date(published)
    return normalize_home_date_text(str(getattr(value, "date_text", "") or ""))


def _parse_iso_date(value: str | date | None) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"日期格式无效：{text}，应为 YYYY-MM-DD") from exc


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


__all__ = [
    "ArticleDateFilter",
    "DateFilterDecision",
    "normalize_home_date_text",
    "parse_target_published_date",
]
