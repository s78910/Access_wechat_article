from __future__ import annotations

from dataclasses import dataclass
import re

from src.modules.window.wechat_document_reader import (
    document_text_lines,
    read_wechat_document_text,
)
from src.modules.window.window_models import WindowInfo


INVALID_ACCOUNT_NAMES = frozenset(
    {
        "微信",
        "wechat",
        "weixin",
        "公众号",
        "服务号",
        "订阅号",
        "全部",
        "贴图",
        "文章",
        "视频号",
        "展开",
        "今天",
        "昨天",
    }
)


@dataclass(frozen=True, slots=True)
class WechatHomeInfo:
    account_name: str
    document_text: str


class WechatHomeReader:
    """从 Chromium Document TextPattern 读取公众号主页身份。"""

    def read(self, home_window: WindowInfo) -> WechatHomeInfo:
        document, text = read_wechat_document_text(home_window.control)
        if document is None:
            raise RuntimeError("公众号主页没有可读 DocumentControl")
        document_name = str(getattr(document, "Name", "") or "").strip()
        candidates = [document_name, *document_text_lines(text)]
        account_name = next((item for item in candidates if _is_account_name(item)), "")
        if not account_name:
            raise RuntimeError("未从公众号主页读取到有效公众号名称")
        return WechatHomeInfo(account_name=account_name, document_text=text)


def _is_account_name(value: str) -> bool:
    text = " ".join(str(value or "").split()).strip()
    if not text or len(text) > 64 or text.lower() in INVALID_ACCOUNT_NAMES or text in INVALID_ACCOUNT_NAMES:
        return False
    # 公众号名称优先来自浏览器标签/主页顶部短文本；文章标题、日期和统计文本不能兜底成名称。
    if _looks_like_article_title(text) or _looks_like_date_text(text):
        return False
    if re.fullmatch(r"(?:\d+篇原创内容|\d+个朋友关注)", text):
        return False
    if text.startswith("阅读") or text.startswith("视频号 :"):
        return False
    if text in {"已关注私信", "已关注", "私信", "正在加载..."}:
        return False
    return True


def _looks_like_article_title(text: str) -> bool:
    if len(text) >= 12 and re.search(r"[，。！？!?：:；;\[\]【】（）()]", text):
        return True
    return False


def _looks_like_date_text(text: str) -> bool:
    if text in {"今天", "昨天"} or re.fullmatch(r"星期[一二三四五六日天]", text):
        return True
    return bool(re.fullmatch(r"(?:\d{4}年)?\d{1,2}月\d{1,2}日", text))
