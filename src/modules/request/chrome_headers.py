from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import urlsplit

import requests


CHROME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

WECHAT_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36 "
    "MicroMessenger/3.9.12.51 WindowsWechat(0x63090c33) "
    "NetType/WIFI Language/zh_CN"
)

DIRECT_REQUEST_PROXIES = {"http": None, "https": None}
WECHAT_ARTICLE_INDEX_URL = "https://mp.weixin.qq.com/s/index.html"

_SEC_CH_UA = '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"'

_CANONICAL_NAMES = {
    "accept": "Accept",
    "accept-language": "Accept-Language",
    "cache-control": "Cache-Control",
    "cookie": "Cookie",
    "origin": "Origin",
    "pragma": "Pragma",
    "referer": "Referer",
    "sec-ch-ua": "Sec-Ch-Ua",
    "sec-ch-ua-mobile": "Sec-Ch-Ua-Mobile",
    "sec-ch-ua-platform": "Sec-Ch-Ua-Platform",
    "sec-fetch-dest": "Sec-Fetch-Dest",
    "sec-fetch-mode": "Sec-Fetch-Mode",
    "sec-fetch-site": "Sec-Fetch-Site",
    "sec-fetch-user": "Sec-Fetch-User",
    "upgrade-insecure-requests": "Upgrade-Insecure-Requests",
    "x-requested-with": "X-Requested-With",
}

_SAFE_OVERRIDE_NAMES = {
    "accept-language",
    "cache-control",
    "cookie",
    "origin",
    "pragma",
    "referer",
    "sec-fetch-dest",
    "sec-fetch-mode",
    "sec-fetch-site",
    "x-requested-with",
}


def build_chrome_document_headers(
    overrides: Mapping[str, Any] | None = None,
    *,
    referer: str | None = None,
) -> dict[str, str]:
    """构造 Chrome 普通页面请求头；用户代理固定为 Chrome。"""
    headers = _base_chrome_headers()
    headers.update(
        {
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8,"
                "application/signed-exchange;v=b3;q=0.7"
            ),
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }
    )
    _apply_safe_overrides(headers, overrides)
    if referer:
        headers["Referer"] = referer
        headers["Sec-Fetch-Site"] = "same-origin"
    return headers


def build_chrome_json_headers(
    overrides: Mapping[str, Any] | None = None,
    *,
    referer: str,
) -> dict[str, str]:
    """构造 Chrome fetch/XHR 风格 JSON 请求头。"""
    headers = _base_chrome_headers()
    headers.update(
        {
            "Accept": "application/json,text/plain,*/*",
            "Referer": referer,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "X-Requested-With": "XMLHttpRequest",
        }
    )
    _apply_safe_overrides(headers, overrides)
    headers["Accept"] = "application/json,text/plain,*/*"
    headers["Referer"] = referer
    return headers


def build_wechat_document_headers(
    overrides: Mapping[str, Any] | None = None,
    *,
    referer: str | None = None,
) -> dict[str, str]:
    """构造微信内置浏览器文章页面请求头。"""
    headers = build_chrome_document_headers(overrides, referer=referer)
    headers["User-Agent"] = WECHAT_BROWSER_USER_AGENT
    return headers


def build_wechat_article_document_headers(
    reference_url: str,
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """构造微信文章主文档导航请求头，避免复用图片、CSS 等资源请求头。"""
    headers = build_wechat_document_headers(overrides)
    headers.update(
        {
            "Cache-Control": "max-age=0",
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/wxpic,image/webp,image/apng,*/*;q=0.8,"
                "application/signed-exchange;v=b3;q=0.7"
            ),
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
            "Upgrade-Insecure-Requests": "1",
        }
    )
    # 刷新或资源请求里带来的条件缓存头会导致 304 或弱化页面内容，离线缓存不继承。
    headers.pop("If-Modified-Since", None)
    headers.pop("If-None-Match", None)
    headers.pop("Pragma", None)
    headers.pop("Sec-Fetch-User", None)

    referer = _document_navigation_referer(
        reference_url,
        _header_value(overrides, "referer"),
    )
    if referer:
        headers["Referer"] = referer

    exportkey = _raw_query_value(reference_url, "exportkey")
    if exportkey:
        headers["exportkey"] = exportkey
    return headers


def build_wechat_json_headers(
    overrides: Mapping[str, Any] | None = None,
    *,
    referer: str,
) -> dict[str, str]:
    """构造微信内置浏览器评论接口请求头。"""
    headers = build_chrome_json_headers(overrides, referer=referer)
    headers["User-Agent"] = WECHAT_BROWSER_USER_AGENT
    return headers


def direct_requests_get(url: str, **kwargs: Any):
    """发起不继承环境代理的直连请求，避免 ALL_PROXY 等变量干扰采集补请求。"""
    session = requests.Session()
    session.trust_env = False
    try:
        return session.get(url, **kwargs)
    finally:
        session.close()


def _base_chrome_headers() -> dict[str, str]:
    return {
        "User-Agent": CHROME_USER_AGENT,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-Ch-Ua": _SEC_CH_UA,
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
    }


def _apply_safe_overrides(headers: dict[str, str], overrides: Mapping[str, Any] | None) -> None:
    for raw_name, raw_value in dict(overrides or {}).items():
        name = str(raw_name).strip().lower()
        value = str(raw_value).strip()
        if (
            name not in _SAFE_OVERRIDE_NAMES
            or not value
            or "\r" in value
            or "\n" in value
        ):
            continue
        headers[_CANONICAL_NAMES[name]] = value


def _header_value(headers: Mapping[str, Any] | None, name: str) -> str:
    wanted = name.strip().lower()
    for raw_key, raw_value in dict(headers or {}).items():
        if str(raw_key).strip().lower() == wanted:
            return str(raw_value).strip()
    return ""


def _document_navigation_referer(reference_url: str, captured_referer: str) -> str:
    if captured_referer:
        parsed = urlsplit(captured_referer)
        if (parsed.hostname or "").lower() != "mp.weixin.qq.com":
            return captured_referer
        path = parsed.path.rstrip("/")
        if path == "/s/index.html":
            return captured_referer
        if path != "/s":
            return captured_referer
    return _wechat_article_index_referer(reference_url)


def _wechat_article_index_referer(reference_url: str) -> str:
    data_version = _raw_query_value(reference_url, "data_version")
    fullversion = _raw_query_value(reference_url, "fasttmpl_fullversion")
    fasttmpl_type = _raw_query_value(reference_url, "fasttmpl_type")
    if not data_version and fullversion:
        data_version = fullversion.split("-", 1)[0]

    pairs: list[tuple[str, str]] = []
    if data_version:
        pairs.append(("data_version", data_version))
    if fullversion:
        pairs.append(("fasttmpl_fullversion", fullversion))
    if fasttmpl_type:
        pairs.append(("fasttmpl_type", fasttmpl_type))
    if not pairs:
        return WECHAT_ARTICLE_INDEX_URL
    query = "&".join(f"{key}={value}" for key, value in pairs)
    return f"{WECHAT_ARTICLE_INDEX_URL}?{query}"


def _raw_query_value(url: str, name: str) -> str:
    wanted = name.strip().lower()
    query = urlsplit(str(url or "")).query
    for part in query.split("&"):
        if not part:
            continue
        key, _, value = part.partition("=")
        if key.strip().lower() == wanted:
            return value.strip()
    return ""
