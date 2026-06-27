from __future__ import annotations

from typing import Any
from urllib.parse import urlparse, urlunparse


def normalize_plain_wechat_short_link(value: Any) -> str:
    """只接受不带任何查询参数的微信文章短链接。"""
    text = str(value or "").strip().strip("'\"").replace("\\/", "/")
    if not text:
        return ""
    parsed = urlparse(text)
    if (parsed.scheme or "").lower() != "https":
        return ""
    if (parsed.hostname or "").lower() != "mp.weixin.qq.com":
        return ""
    if parsed.query or parsed.params or parsed.fragment:
        return ""
    path = parsed.path.rstrip("/")
    if not path.startswith("/s/"):
        return ""
    slug = path.removeprefix("/s/").strip("/")
    if not slug:
        return ""
    return urlunparse(("https", "mp.weixin.qq.com", f"/s/{slug}", "", "", ""))


__all__ = ["normalize_plain_wechat_short_link"]
