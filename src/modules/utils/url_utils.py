from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


SENSITIVE_QUERY_KEYS = {
    "key",
    "pass_ticket",
    "uin",
    "exportkey",
    "sessionid",
    "devicetype",
    "version",
    "appmsg_token",
}


def redact_url(url: str) -> str:
    """隐藏微信文章 URL 中短时间有效的敏感参数，日志和 JSON 中默认只保存脱敏版本。"""
    parsed = urlparse(str(url or ""))
    pairs = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        pairs.append((key, "<redacted>" if key in SENSITIVE_QUERY_KEYS else value))
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(pairs, doseq=True),
            parsed.fragment,
        )
    )


__all__ = ["SENSITIVE_QUERY_KEYS", "redact_url"]
