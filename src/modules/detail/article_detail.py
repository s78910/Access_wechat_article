from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from src.modules.detail.account_identity import is_valid_account_name_text


DEFAULT_TIMEOUT_SECONDS = 10.0
SENSITIVE_QUERY_KEYS = {
    "key",
    "pass_ticket",
    "appmsg_token",
    "cookie",
    "set-cookie",
    "uin",
    "wxtoken",
    "exportkey",
    "sessionid",
}
DETAIL_FIELD_NAMES = (
    "account_name",
    "article_title",
    "published_article_time",
    "short_link",
    "url_redacted",
    "audience_count",
    "read_count",
    "like_count",
    "share_count",
    "recommend_count",
    "comment_count",
    "collect_time",
)
METRIC_KEY_MAP = {
    "audience_count": ("tts_heard_person_cnt", "audience_count", "ori_read_num"),
    "read_count": ("read_num", "read_num_new", "real_read_num"),
    "like_count": ("old_like_num", "old_like_count"),
    "share_count": ("share_num", "share_count"),
    "recommend_count": ("like_count", "like_num", "recommend_count"),
    "comment_count": ("comment_count", "elected_comment_total_cnt"),
}


class ArticleDetailFetchError(RuntimeError):
    """文章详情获取失败，调用方据此跳过 article_detail.json 和 SQLite 写入。"""


FetchHtmlCallable = Callable[[str, dict[str, str], float], str]


def build_keyed_article_url(
    biz: str,
    mid: str,
    idx: str,
    sn: str,
    key: str,
    *,
    pass_ticket: str = "",
    host: str = "mp.weixin.qq.com",
    path: str = "/s",
    extra_params: dict[str, Any] | None = None,
) -> str:
    """通过关键参数组装微信文章带 key 的主请求 URL，方便后续独立调试调用。"""
    params: list[tuple[str, str]] = [
        ("__biz", str(biz or "")),
        ("mid", str(mid or "")),
        ("idx", str(idx or "1")),
        ("sn", str(sn or "")),
        ("key", str(key or "")),
    ]
    if pass_ticket:
        params.append(("pass_ticket", str(pass_ticket)))
    for name, value in dict(extra_params or {}).items():
        if value not in (None, ""):
            params.append((str(name), str(value)))
    return urlunparse(("https", host, path or "/s", "", urlencode(params), ""))


def fetch_article_detail_to_file(
    keyed_url: str,
    article_dir: Path | str,
    *,
    request_headers: dict[str, Any] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    collect_time: str | None = None,
    fetch_html: FetchHtmlCallable | None = None,
) -> dict[str, Any]:
    """请求带 key URL 并把结构化详情写到单篇文章归档目录下的 article_detail.json。"""
    detail = fetch_article_detail_from_keyed_url(
        keyed_url,
        request_headers=request_headers,
        timeout_seconds=timeout_seconds,
        collect_time=collect_time,
        fetch_html=fetch_html,
    )
    detail_path = write_article_detail_json(detail, article_dir)
    return {"article_detail_path": str(detail_path), "detail": detail}


def fetch_article_detail_from_keyed_url(
    keyed_url: str,
    *,
    request_headers: dict[str, Any] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    collect_time: str | None = None,
    fetch_html: FetchHtmlCallable | None = None,
) -> dict[str, Any]:
    """使用 requests 重新访问带 key URL，并从响应 HTML 中提取文章详情。"""
    url = str(keyed_url or "").strip()
    if not url:
        raise ArticleDetailFetchError("缺少带 key 的文章 URL")
    html_text = (
        fetch_html(url, normalize_request_headers(request_headers), normalize_timeout(timeout_seconds))
        if fetch_html
        else request_article_html(url, request_headers=request_headers, timeout_seconds=timeout_seconds)
    )
    detail = build_article_detail_from_html(html_text, url, collect_time=collect_time)
    # 内部字段只在主流程内传递，供评论接口从同一份 HTML 提取 comment_id，不写入 article_detail.json。
    detail["_source_html"] = html_text
    return detail


def request_article_html(
    keyed_url: str,
    *,
    request_headers: dict[str, Any] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """实际发送 requests 请求；只返回响应文本，不落盘保存原始请求或响应。"""
    try:
        import requests
    except ModuleNotFoundError as exc:
        raise ArticleDetailFetchError("当前 Python 环境缺少 requests，请先安装 requirements.txt 中的依赖") from exc

    headers = normalize_request_headers(request_headers)
    try:
        response = requests.get(str(keyed_url), headers=headers, timeout=normalize_timeout(timeout_seconds))
    except requests.RequestException as exc:
        raise ArticleDetailFetchError(f"请求文章详情失败：{exc}") from exc

    if response.status_code < 200 or response.status_code >= 300:
        raise ArticleDetailFetchError(f"请求文章详情失败：HTTP {response.status_code}")
    return response.text


def build_article_detail_from_html(html_text: str, keyed_url: str, *, collect_time: str | None = None) -> dict[str, Any]:
    """从文章 HTML 中提取最终 article_detail.json 需要的扁平字段。"""
    text = str(html_text or "")
    short_link = extract_wechat_short_link(text)
    if not short_link:
        raise ArticleDetailFetchError("未从文章响应中解析到短链接 https://mp.weixin.qq.com/s/xxxx")

    metrics = extract_article_metrics(text)
    detail = {
        "account_name": extract_account_name(text),
        "article_title": extract_article_title(text),
        "published_article_time": extract_published_article_time(text),
        "short_link": short_link,
        "url_redacted": redact_sensitive_url(keyed_url),
        "audience_count": metrics["audience_count"],
        "read_count": metrics["read_count"],
        "like_count": metrics["like_count"],
        "share_count": metrics["share_count"],
        "recommend_count": metrics["recommend_count"],
        "comment_count": metrics["comment_count"],
        "collect_time": collect_time or current_time_text(),
    }
    return {field: detail.get(field) for field in DETAIL_FIELD_NAMES}


def write_article_detail_json(detail: dict[str, Any], article_dir: Path | str) -> Path:
    """把详情 JSON 写入调用方确定好的单篇文章目录。"""
    target_dir = Path(article_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    detail_path = target_dir / "article_detail.json"
    public_detail = {field: dict(detail or {}).get(field) for field in DETAIL_FIELD_NAMES}
    detail_path.write_text(json.dumps(public_detail, ensure_ascii=False, indent=2), encoding="utf-8")
    return detail_path


def normalize_request_headers(headers: dict[str, Any] | None) -> dict[str, str]:
    excluded = {
        ":authority",
        ":method",
        ":path",
        ":scheme",
        "host",
        "content-length",
        "connection",
        "proxy-connection",
        "transfer-encoding",
        "upgrade",
        "te",
        "trailer",
    }
    result: dict[str, str] = {}
    for key, value in dict(headers or {}).items():
        name = str(key).lower()
        if name in excluded or value in (None, ""):
            continue
        if "\r" in name or "\n" in name:
            continue
        text = str(value)
        if "\r" in text or "\n" in text:
            continue
        if name == "accept-encoding":
            # requests 会自动协商压缩；复用 HTTP/2 场景中的 br 等值容易增加解码不确定性。
            continue
        if name:
            result[name] = text
    result.setdefault("user-agent", "Mozilla/5.0 MicroMessenger")
    return result


def normalize_timeout(value: Any) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS
    if seconds <= 0:
        return DEFAULT_TIMEOUT_SECONDS
    return DEFAULT_TIMEOUT_SECONDS if seconds > 30 else seconds


def extract_account_name(html_text: str) -> str:
    return first_valid_match_text(
        html_text,
        (
            r"var\s+nickname\s*=\s*['\"](?P<value>.*?)['\"]",
            r"\bnickname\s*:\s*['\"](?P<value>.*?)['\"]",
            r"var\s+profile_nickname\s*=\s*['\"](?P<value>.*?)['\"]",
            r"\bprofile_nickname\s*:\s*['\"](?P<value>.*?)['\"]",
            r"(?is)<[^>]+id=['\"]js_name['\"][^>]*>(?P<value>.*?)</[^>]+>",
            r"(?i)<meta[^>]+property=['\"]og:article:author['\"][^>]+content=['\"](?P<value>.*?)['\"]",
            r"(?i)<meta[^>]+name=['\"]author['\"][^>]+content=['\"](?P<value>.*?)['\"]",
        ),
        is_valid_account_name_text,
    )


def extract_article_title(html_text: str) -> str:
    return first_match_text(
        html_text,
        (
            r"var\s+msg_title\s*=\s*['\"](?P<value>.*?)['\"]",
            r"var\s+appmsg_title\s*=\s*['\"](?P<value>.*?)['\"]",
            r"(?i)<meta[^>]+property=['\"]og:title['\"][^>]+content=['\"](?P<value>.*?)['\"]",
            r"(?i)<meta[^>]+name=['\"]twitter:title['\"][^>]+content=['\"](?P<value>.*?)['\"]",
            r"(?is)<h1[^>]+id=['\"]activity-name['\"][^>]*>(?P<value>.*?)</h1>",
            r"(?is)<title[^>]*>(?P<value>.*?)</title>",
        ),
    )


def extract_published_article_time(html_text: str) -> str:
    ct_match = re.search(r"var\s+ct\s*=\s*['\"](?P<value>\d{8,})['\"]", str(html_text or ""))
    if ct_match:
        return normalize_published_article_time(ct_match.group("value"))
    value = first_match_text(
        html_text,
        (
            r"var\s+publish_time\s*=\s*['\"](?P<value>[^'\"]+)['\"]",
            r"\bpublish_time\s*:\s*['\"](?P<value>[^'\"]+)['\"]",
            r"var\s+ori_create_time\s*=\s*['\"](?P<value>\d{8,})['\"]",
        ),
    )
    return normalize_published_article_time(value)


def normalize_published_article_time(value: Any) -> str:
    text = normalize_text(value).replace("T", " ")
    if not text:
        return ""
    if re.fullmatch(r"\d{8,}", text):
        try:
            return datetime.fromtimestamp(int(text)).strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError, OSError):
            return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", text):
        return text
    if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}.*", text):
        return text[:16]
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}) (\d{2})-(\d{2})", text)
    if match:
        return f"{match.group(1)} {match.group(2)}:{match.group(3)}"
    return text


def extract_wechat_short_link(html_text: str) -> str:
    """只接受明确短链字段，避免把页面里的帮助/争议说明链接误认为文章短链。"""
    text = str(html_text or "")
    patterns = (
        r"(?:window\.)?short_link\s*=\s*['\"](?P<value>.*?)['\"]",
        r"var\s+short_link\s*=\s*['\"](?P<value>.*?)['\"]",
        r"(?i)<meta[^>]+property=['\"]og:url['\"][^>]+content=['\"](?P<value>.*?)['\"]",
        r"(?i)<link[^>]+rel=['\"]canonical['\"][^>]+href=['\"](?P<value>.*?)['\"]",
    )
    for pattern in patterns:
        value = first_match_text(text, (pattern,))
        short_link = normalize_wechat_short_link(value)
        if short_link:
            return short_link
    return ""


def normalize_wechat_short_link(value: Any) -> str:
    text = normalize_text(value).strip("'\"")
    if not text:
        return ""
    parsed = urlparse(text)
    if (parsed.scheme or "").lower() != "https":
        return ""
    if (parsed.hostname or "").lower() != "mp.weixin.qq.com":
        return ""
    slug = parsed.path.rstrip("/").removeprefix("/s/").strip("/")
    if not slug or parsed.path.rstrip("/") != f"/s/{slug}":
        return ""
    return urlunparse(("https", "mp.weixin.qq.com", f"/s/{slug}", "", "", ""))


def extract_article_metrics(html_text: str) -> dict[str, int | None]:
    return {
        output_key: first_int(extract_numeric_value(html_text, source_key) for source_key in source_keys)
        for output_key, source_keys in METRIC_KEY_MAP.items()
    }


def extract_numeric_value(html_text: str, key: str) -> int | None:
    escaped_key = re.escape(key)
    key_pattern = rf"(?<![A-Za-z0-9_])[\"']?{escaped_key}[\"']?(?![A-Za-z0-9_])"
    patterns = (
        rf"{key_pattern}\s*[:=]\s*[\"'](?P<value>\d+)[\"']\s*\*\s*1",
        rf"{key_pattern}\s*[:=]\s*(?P<value>\d+)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, str(html_text or ""))
        if match:
            return int(match.group("value"))
    return None


def first_match_text(text: str, patterns: tuple[str, ...]) -> str:
    source = str(text or "")
    for pattern in patterns:
        match = re.search(pattern, source)
        if not match:
            continue
        value = match.group("value") if "value" in match.groupdict() else match.group(0)
        cleaned = normalize_text(re.sub(r"<[^>]+>", "", value))
        if cleaned:
            return cleaned
    return ""


def first_valid_match_text(text: str, patterns: tuple[str, ...], validator) -> str:
    source = str(text or "")
    for pattern in patterns:
        for match in re.finditer(pattern, source):
            value = match.group("value") if "value" in match.groupdict() else match.group(0)
            cleaned = normalize_text(re.sub(r"<[^>]+>", "", value))
            if cleaned and validator(cleaned):
                return cleaned
    return ""


def normalize_text(value: Any) -> str:
    return (
        html.unescape(str(value or ""))
        .replace("\\/", "/")
        .replace("\\x26", "&")
        .replace("\\u0026", "&")
        .strip()
    )


def first_int(values: Any) -> int | None:
    for value in values:
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def redact_sensitive_url(url: str) -> str:
    parsed = urlparse(str(url or ""))
    pairs = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        pairs.append((key, "***" if key.lower() in SENSITIVE_QUERY_KEYS else value))
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(pairs), parsed.fragment))


def current_time_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
