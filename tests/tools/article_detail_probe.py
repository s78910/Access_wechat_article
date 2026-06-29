from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


METRIC_KEY_MAP = {
    "audience_count": ("tts_heard_person_cnt", "audience_count", "ori_read_num"),
    "read_count": ("read_num", "read_num_new", "real_read_num"),
    "like_count": ("old_like_num", "old_like_count"),
    "share_count": ("share_num", "share_count"),
    "recommend_count": ("like_num", "like_count", "recommend_count"),
    "comment_count": ("comment_count", "elected_comment_total_cnt"),
}
SENSITIVE_KEYS = {"key", "pass_ticket", "appmsg_token", "cookie", "set-cookie", "uin", "wxtoken"}


def extract_detail_runtime_context(url: str, html_text: str) -> dict[str, Any]:
    """从文章 URL 和主 HTML 中提取后续详情接口所需参数。"""
    parsed_query = parse_qs(urlparse(str(url or "")).query, keep_blank_values=True)
    context: dict[str, Any] = {}
    for key in ("__biz", "biz", "mid", "appmsgid", "idx", "sn", "key", "pass_ticket", "appmsg_token"):
        value = first_query_value(parsed_query, key)
        if value:
            context[normalize_context_key(key)] = value

    text = str(html_text or "")
    html_pairs = extract_js_string_pairs(text)
    alias_map = {
        "biz": "__biz",
        "__biz": "__biz",
        "mid": "mid",
        "appmsgid": "mid",
        "appmsg_id": "mid",
        "idx": "idx",
        "itemidx": "idx",
        "sn": "sn",
        "key": "key",
        "pass_ticket": "pass_ticket",
        "appmsg_token": "appmsg_token",
    }
    for key, value in html_pairs.items():
        normalized_key = alias_map.get(key.lower())
        if normalized_key and value and is_valid_runtime_context_value(normalized_key, value):
            # URL 中的 __biz/mid/idx/sn 才是当前文章身份；HTML 里可能混有音频、转载或嵌入对象的同名字段。
            if normalized_key in {"__biz", "mid", "idx", "sn"} and context.get(normalized_key):
                continue
            context[normalized_key] = value

    context["article_title"] = first_non_empty(
        html_pairs.get("msg_title"),
        html_pairs.get("appmsg_title"),
        html_pairs.get("article_title"),
        extract_h1_title(text),
    )
    context["published_article_time"] = first_non_empty(
        html_pairs.get("publish_time"),
        html_pairs.get("ct"),
        html_pairs.get("ori_create_time"),
    )
    return {key: value for key, value in context.items() if value not in (None, "")}


def build_getappmsgext_request(context: dict[str, Any], request_headers: dict[str, Any]) -> dict[str, Any]:
    """构造文章扩展统计接口请求；只返回请求描述，由调用方决定是否发送。"""
    biz = first_non_empty(context.get("__biz"), context.get("biz"))
    mid = first_non_empty(context.get("mid"), context.get("appmsgid"))
    idx = str(context.get("idx") or "1")
    url = urlunparse(
        (
            "https",
            "mp.weixin.qq.com",
            "/mp/getappmsgext",
            "",
            urlencode({"f": "json", "mock": context.get("mock") or ""}),
            "",
        )
    )
    headers = build_ajax_headers(request_headers, referer=str(context.get("request_url") or ""))
    data = urlencode(
        {
            "r": context.get("random") or "",
            "__biz": biz,
            "appmsg_type": context.get("appmsg_type") or "9",
            "appmsgid": mid,
            "mid": mid,
            "sn": context.get("sn") or "",
            "idx": idx,
            "itemidx": idx,
            "scene": context.get("scene") or "0",
            "subscene": context.get("subscene") or "0",
            "ascene": context.get("ascene") or "0",
            "title": context.get("article_title") or "",
            "ct": context.get("published_article_time") or "",
            "abtest_cookie": context.get("abtest_cookie") or "",
            "devicetype": context.get("devicetype") or "",
            "version": context.get("version") or "",
            "is_need_ticket": context.get("is_need_ticket") or "0",
            "is_need_ad": context.get("is_need_ad") or "0",
            "comment_id": context.get("comment_id") or "",
            "is_need_reward": context.get("is_need_reward") or "0",
            "both_ad": context.get("both_ad") or "0",
            "reward_uin_count": context.get("reward_uin_count") or "0",
            "send_time": context.get("send_time") or "",
            "msg_daily_idx": context.get("msg_daily_idx") or "",
            "is_original": context.get("is_original") or "0",
            "is_only_read": "1",
            "req_id": context.get("req_id") or "",
            "pass_ticket": context.get("pass_ticket") or "",
            "is_temp_url": "0",
            "item_show_type": context.get("item_show_type") or "",
            "tmp_version": "1",
            "more_read_type": context.get("more_read_type") or "0",
            "appmsg_like_type": context.get("appmsg_like_type") or "1",
            "is_pay_subscribe": context.get("is_pay_subscribe") or "0",
            "pay_subscribe_uin_count": context.get("pay_subscribe_uin_count") or "0",
            "has_red_packet_cover": context.get("has_red_packet_cover") or "0",
        }
    )
    return {"method": "POST", "url": url, "headers": headers, "data": data}


def fetch_request(request: dict[str, Any], *, timeout_seconds: float = 10.0) -> dict[str, Any]:
    """发送诊断请求并返回精简响应，不把完整敏感请求写入日志。"""
    try:
        import requests
    except ModuleNotFoundError as exc:
        raise RuntimeError("当前 Python 环境缺少 requests，请先安装 requirements.txt 中的依赖。") from exc

    method = str(request.get("method") or "GET").upper()
    url = str(request.get("url") or "")
    headers = dict(request.get("headers") or {})
    data = request.get("data")
    response = requests.request(method, url, headers=headers, data=data, timeout=max(1.0, float(timeout_seconds)))
    text = response.text
    parsed_json = try_parse_json(text)
    return {
        "url": url,
        "url_redacted": redact_sensitive_url(url),
        "method": method,
        "status_code": response.status_code,
        "content_type": response.headers.get("content-type", ""),
        "text": text,
        "json": parsed_json,
        "metrics": normalize_metric_payload(parsed_json if parsed_json is not None else text),
    }


def normalize_metric_payload(payload: Any) -> dict[str, int | None]:
    """把微信统计接口或主 HTML 中的计数字段统一成 article_detail.stats 字段。"""
    flattened = flatten_payload(payload)
    return {
        output_key: first_int(flattened.get(source_key) for source_key in source_keys)
        for output_key, source_keys in METRIC_KEY_MAP.items()
    }


def extract_metric_assignments_from_html(html_text: str) -> dict[str, int]:
    """扫描主 HTML 中真实的统计数字赋值；微信常见的空占位 `'' * 1` 不计入结果。"""
    result: dict[str, int] = {}
    text = str(html_text or "")
    for key in {source for sources in METRIC_KEY_MAP.values() for source in sources}:
        escaped_key = re.escape(key)
        key_pattern = rf"(?<![A-Za-z0-9_])[\"']?{escaped_key}[\"']?(?![A-Za-z0-9_])"
        patterns = (
            rf"{key_pattern}\s*[:=]\s*[\"'](?P<value>\d+)[\"']\s*\*\s*1",
            rf"{key_pattern}\s*[:=]\s*(?P<value>\d+)\b",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                result[key] = int(match.group("value"))
                break
    return result


def merge_metric_sources(primary: dict[str, int | None], fallback: dict[str, int | None]) -> dict[str, int | None]:
    merged: dict[str, int | None] = {}
    for key in METRIC_KEY_MAP:
        merged[key] = primary.get(key) if primary.get(key) is not None else fallback.get(key)
    return merged


def load_request_context(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"请求上下文不是 JSON 对象：{path}")
    return data


def probe_from_request_context(path: Path, *, timeout_seconds: float = 10.0) -> dict[str, Any]:
    """从 original_request.json 一类文件发起诊断，适合测试阶段手动调用。"""
    request_context = load_request_context(path)
    url = str(request_context.get("url") or request_context.get("request_url") or "")
    headers = dict(request_context.get("request_headers") or {})
    main_request = {"method": request_context.get("method") or "GET", "url": url, "headers": headers}
    main_response = fetch_request(main_request, timeout_seconds=timeout_seconds)
    context = extract_detail_runtime_context(url, main_response.get("text") or "")
    context["request_url"] = url
    metric_request = build_getappmsgext_request(context, headers)
    metric_response = fetch_request(metric_request, timeout_seconds=timeout_seconds)
    html_metrics = normalize_metric_payload(extract_metric_assignments_from_html(main_response.get("text") or ""))
    metric_response_metrics = metric_response.get("metrics") or {}
    return {
        "request_context_path": str(path),
        "main_response": strip_response_body_for_report(main_response),
        "runtime_context": redact_sensitive_mapping(context),
        "html_metrics": html_metrics,
        "metric_request": redact_request_for_report(metric_request),
        "metric_response": strip_response_body_for_report(metric_response),
        "metric_response_metrics": metric_response_metrics,
        "metrics": merge_metric_sources(metric_response_metrics, html_metrics),
    }


def build_ajax_headers(request_headers: dict[str, Any], *, referer: str = "") -> dict[str, str]:
    keep_names = {"user-agent", "cookie", "accept-language", "referer"}
    headers = {
        str(key).lower(): str(value)
        for key, value in dict(request_headers or {}).items()
        if str(key).lower() in keep_names and str(value)
    }
    headers.setdefault("accept", "application/json, text/javascript, */*; q=0.01")
    headers.setdefault("content-type", "application/x-www-form-urlencoded; charset=UTF-8")
    headers["x-requested-with"] = "XMLHttpRequest"
    if referer:
        headers["referer"] = referer
    return headers


def extract_js_string_pairs(text: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    patterns = (
        r"\b(?:var\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\b\s*=\s*['\"](?P<value>[^'\"]{0,1000})['\"]",
        r"['\"](?P<key>[A-Za-z_][A-Za-z0-9_]*)['\"]\s*:\s*['\"](?P<value>[^'\"]{0,1000})['\"]",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, str(text or "")):
            pairs[match.group("key")] = normalize_text_value(match.group("value"))
    return pairs


def extract_h1_title(text: str) -> str:
    match = re.search(r"(?is)<h1[^>]+id=['\"]activity-name['\"][^>]*>(?P<value>.*?)</h1>", str(text or ""))
    if not match:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(match.group("value")))).strip()


def flatten_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, str):
        parsed = try_parse_json(payload)
        if parsed is None:
            return extract_numeric_pairs_from_text(payload)
        payload = parsed
    result: dict[str, Any] = {}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                result[str(key)] = item
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    return result


def extract_numeric_pairs_from_text(text: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for key in {source for sources in METRIC_KEY_MAP.values() for source in sources}:
        pattern = rf"[\"']?{re.escape(key)}[\"']?\s*[:=]\s*[\"']?(?P<value>\d+)[\"']?"
        match = re.search(pattern, str(text or ""))
        if match:
            result[key] = int(match.group("value"))
    return result


def first_query_value(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key) or []
    return str(values[0]) if values else ""


def normalize_context_key(key: str) -> str:
    return "mid" if key == "appmsgid" else key


def is_valid_runtime_context_value(key: str, value: Any) -> bool:
    text = normalize_text_value(value)
    if not text:
        return False
    if any(fragment in text for fragment in (").concat(", "opts.", "${", "function(", "return ")):
        return False
    if key in {"mid", "idx"}:
        return bool(re.fullmatch(r"\d+", text))
    return True


def normalize_text_value(value: Any) -> str:
    return html.unescape(str(value or "")).replace("\\/", "/").replace("\\u0026", "&").strip()


def first_non_empty(*values: Any) -> str:
    for value in values:
        text = normalize_text_value(value)
        if text:
            return text
    return ""


def first_int(values: Any) -> int | None:
    for value in values:
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def try_parse_json(text: Any) -> Any | None:
    if isinstance(text, (dict, list)):
        return text
    try:
        return json.loads(str(text or ""))
    except json.JSONDecodeError:
        return None


def redact_sensitive_url(url: str) -> str:
    parsed = urlparse(str(url or ""))
    query_items = []
    for key, values in parse_qs(parsed.query, keep_blank_values=True).items():
        query_items.append((key, "***" if key.lower() in SENSITIVE_KEYS else values[0] if values else ""))
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query_items), parsed.fragment))


def redact_sensitive_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for key, value in dict(mapping or {}).items():
        lowered = str(key).lower()
        result[key] = "***" if lowered in SENSITIVE_KEYS else value
    return result


def redact_request_for_report(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "method": request.get("method"),
        "url_redacted": redact_sensitive_url(str(request.get("url") or "")),
        "headers": redact_sensitive_mapping(dict(request.get("headers") or {})),
        "data": str(request.get("data") or ""),
    }


def strip_response_body_for_report(response: dict[str, Any]) -> dict[str, Any]:
    text = str(response.get("text") or "")
    return {
        "method": response.get("method"),
        "url_redacted": response.get("url_redacted") or redact_sensitive_url(str(response.get("url") or "")),
        "status_code": response.get("status_code"),
        "content_type": response.get("content_type"),
        "body_chars": len(text),
        "body_preview": text[:500],
        "metrics": response.get("metrics") or {},
    }
