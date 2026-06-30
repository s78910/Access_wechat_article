from __future__ import annotations

import hashlib
import html
import json
import mimetypes
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlunparse

from src.modules.detail.article_detail import (
    extract_account_name,
    extract_article_title,
    extract_published_article_time,
    normalize_request_headers,
    redact_sensitive_url,
)


DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_RESOURCE_TIMEOUT_SECONDS = 5.0
DEFAULT_COMMENT_LIMIT = 100
DEFAULT_REPLY_LIMIT = 20
DEFAULT_MAX_BODY_CHARS = 8_000_000
MAX_RESOURCE_BYTES = 2_000_000
COMMENT_LIST_KEYS = (
    "comment",
    "comment_list",
    "elected_comment",
    "elected_comment_list",
    "friend_comment",
    "my_comment",
)
RESOURCE_HEADERS = {
    "accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "user-agent": "Mozilla/5.0 MicroMessenger",
}

HttpGetCallable = Callable[[str, dict[str, str], float], Any]


class CommentFetchError(RuntimeError):
    """评论获取失败；调用方可以把消息直接写入运行日志。"""


def fetch_comments_to_archive(
    keyed_url: str,
    html_text: str,
    article_dir: Path | str,
    *,
    request_headers: dict[str, Any] | None = None,
    collect_time: str | None = None,
    comment_limit: int = DEFAULT_COMMENT_LIMIT,
    comment_max_pages: int = 0,
    reply_limit: int = DEFAULT_REPLY_LIMIT,
    reply_max_pages_per_comment: int = 0,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_body_chars: int = DEFAULT_MAX_BODY_CHARS,
    page_pause_seconds: float = 0.2,
    reply_page_pause_seconds: float = 0.2,
    download_resources: bool = True,
    download_avatars: bool = True,
    download_emojis: bool = True,
    download_pictures: bool = True,
    resource_timeout_seconds: float = DEFAULT_RESOURCE_TIMEOUT_SECONDS,
    http_get: HttpGetCallable | None = None,
    resource_get: HttpGetCallable | None = None,
) -> dict[str, Any]:
    """按微信评论接口可返回范围抓取评论，并写入单篇文章归档目录。"""
    article_url = str(keyed_url or "").strip()
    if not article_url:
        raise CommentFetchError("缺少带 key 的文章 URL，无法请求评论接口")

    target_dir = Path(article_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    started_at = time.time()
    headers = normalize_comment_request_headers(request_headers, referer=article_url)
    page_payloads: list[dict[str, Any]] = []
    page_summaries: list[dict[str, Any]] = []
    seen_comment_ids: set[str] = set()
    current_offset = 0
    comment_buffer = ""
    max_pages = max(0, int(comment_max_pages or 0))
    limit = max(1, int(comment_limit or DEFAULT_COMMENT_LIMIT))
    stop_reason = "not_started"
    pagination_complete = False
    continue_flag_final: bool | None = None
    getter = http_get or requests_get

    page_index = 0
    while True:
        if max_pages and page_index >= max_pages:
            stop_reason = "max_pages_reached"
            break
        comment_url = build_comment_page_url(
            article_url,
            html_text,
            request_headers or {},
            limit=limit,
            offset=current_offset,
            buffer=comment_buffer,
        )
        if not comment_url:
            stop_reason = "cannot_build_comment_url"
            break

        page = request_json(
            comment_url,
            headers=headers,
            timeout_seconds=timeout_seconds,
            max_body_chars=max_body_chars,
            http_get=getter,
        )
        parsed = page.get("json")
        if isinstance(parsed, dict):
            page_payloads.append(parsed)
        page_new_count = count_new_comment_items(parsed, seen_comment_ids)
        page_summaries.append(
            {
                "page_index": page_index,
                "offset": current_offset,
                "limit": limit,
                "ok": page.get("ok", False),
                "status_code": page.get("status_code"),
                "new_comment_count": page_new_count,
                "url_redacted": redact_sensitive_url(comment_url),
                "error": page.get("error", ""),
            }
        )

        if not page.get("ok") or not isinstance(parsed, dict):
            stop_reason = "page_fetch_failed"
            break

        continue_flag_final = safe_bool(parsed.get("continue_flag"))
        if parsed.get("buffer") not in (None, ""):
            comment_buffer = str(parsed.get("buffer") or "")
        if continue_flag_final is False:
            stop_reason = "continue_flag_false"
            pagination_complete = True
            break
        if page_new_count <= 0 and page_index > 0:
            stop_reason = "no_new_comments"
            pagination_complete = True
            break
        current_offset += page_new_count
        page_index += 1
        if page_pause_seconds > 0:
            time.sleep(max(0.0, float(page_pause_seconds)))

    merged = merge_comment_pages(page_payloads)
    reply_fetch = fetch_all_comment_replies(
        article_url=article_url,
        html_text=html_text,
        request_headers=request_headers or {},
        merged_comments=merged,
        headers=headers,
        http_get=getter,
        reply_limit=reply_limit,
        reply_max_pages_per_comment=reply_max_pages_per_comment,
        timeout_seconds=timeout_seconds,
        max_body_chars=max_body_chars,
        reply_page_pause_seconds=reply_page_pause_seconds,
    )
    comments = extract_structured_comments(merged)
    resource_result = (
        download_comment_resources(
            comments,
            target_dir,
            resource_get=resource_get,
            download_avatars=download_avatars,
            download_emojis=download_emojis,
            download_pictures=download_pictures,
            timeout_seconds=resource_timeout_seconds,
        )
        if download_resources
        else {"attempted": False, "reason": "download_resources_disabled", "resources": {}, "counts": empty_resource_counts()}
    )
    summary = build_comment_summary(
        merged,
        comments,
        page_summaries=page_summaries,
        pagination_complete=pagination_complete,
        stop_reason=stop_reason,
        continue_flag_final=continue_flag_final,
        reply_fetch=reply_fetch,
        resource_result=resource_result,
    )
    package = {
        "schema_version": "wechat_comments_v1",
        "created_at": collect_time or current_time_text(),
        "article": {
            "account_name": extract_account_name(html_text),
            "article_title": extract_article_title(html_text),
            "published_article_time": extract_published_article_time(html_text),
            "url_redacted": redact_sensitive_url(article_url),
        },
        "summary": summary,
        "comments": comments,
    }
    final_path = target_dir / "comments_final.json"
    final_path.write_text(json.dumps(package, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    return {
        "attempted": True,
        "ok": bool(page_payloads),
        "comments_final_json_path": str(final_path),
        "elapsed_seconds": round(time.time() - started_at, 3),
        "comment_count": summary["top_level_comment_count"],
        "reply_count": summary["reply_count"],
        "total_message_count": summary["total_message_count"],
        "reply_missing_count": summary["reply_missing_count"],
        "pagination_complete": pagination_complete,
        "stop_reason": stop_reason,
        "comment_page_count": len(page_payloads),
        "comment_resource_counts": resource_result.get("counts", {}),
        "reply_fetch": reply_fetch,
    }


def build_comment_page_url(
    article_url: str,
    html_text: str,
    request_headers: dict[str, Any] | None,
    *,
    limit: int,
    offset: int,
    buffer: str = "",
) -> str:
    """构造一级评论分页 URL；后续页携带微信返回的 buffer，减少漏页。"""
    identity = extract_comment_identity(article_url, html_text, request_headers)
    params: list[tuple[str, str]] = [
        ("action", "getcomment"),
        ("__biz", identity.get("biz", "")),
        ("appmsgid", identity.get("mid", "")),
        ("idx", identity.get("idx", "")),
        ("comment_id", identity.get("comment_id", "")),
        ("offset", str(max(0, int(offset)))),
        ("limit", str(max(1, int(limit)))),
        ("uin", identity.get("uin", "")),
        ("key", identity.get("key", "")),
        ("pass_ticket", identity.get("pass_ticket", "")),
        ("wxtoken", identity.get("wxtoken", "") or "777"),
        ("devicetype", identity.get("devicetype", "")),
        ("clientversion", identity.get("clientversion", "")),
        ("appmsg_token", identity.get("appmsg_token", "")),
        ("comment_scene", identity.get("comment_scene", "")),
        ("scene", identity.get("scene", "")),
        ("subscene", identity.get("subscene", "")),
        ("send_time", identity.get("send_time", "")),
        ("sessionid", identity.get("sessionid", "")),
        ("enterid", identity.get("enterid", "")),
        ("ascene", identity.get("ascene", "")),
        ("lang", identity.get("lang", "")),
        ("countrycode", identity.get("countrycode", "")),
        ("x5", identity.get("x5", "") or "0"),
        ("f", "json"),
    ]
    if buffer:
        params.append(("buffer", str(buffer)))
    compact = [(key, value) for key, value in params if value not in ("", None)]
    required = {"__biz", "appmsgid", "idx", "comment_id"}
    if not required.issubset({key for key, value in compact if value}):
        return ""
    parsed = urlparse(article_url)
    return urlunparse((parsed.scheme or "https", parsed.netloc or "mp.weixin.qq.com", "/mp/appmsg_comment", "", urlencode(compact, doseq=True), ""))


def build_comment_reply_url(
    article_url: str,
    html_text: str,
    request_headers: dict[str, Any] | None,
    comment: dict[str, Any],
    *,
    limit: int,
    offset: int,
    buffer: str,
    max_reply_id: str,
    filter_reply_ids: list[str],
) -> str:
    identity = extract_comment_identity(article_url, html_text, request_headers)
    params: list[tuple[str, str]] = [
        ("action", "getcommentreply"),
        ("__biz", identity.get("biz", "")),
        ("appmsgid", identity.get("mid", "")),
        ("idx", identity.get("idx", "")),
        ("comment_id", identity.get("comment_id", "")),
        ("content_id", str(comment.get("content_id") or "")),
        ("id", str(comment.get("id") or comment.get("comment_id") or "")),
        ("r", str(time.time())),
        ("limit", str(max(1, int(limit)))),
        ("offset", str(max(0, int(offset)))),
        ("buffer", buffer),
        ("is_first", "0" if offset else "1"),
        ("max_reply_id", max_reply_id),
        ("sessionid", identity.get("sessionid", "")),
        ("enterid", identity.get("enterid", "") or "0"),
        ("comment_nickname", str(comment.get("nick_name") or comment.get("nickname") or "")),
        ("comment_headurl", str(comment.get("logo_url") or comment.get("avatar_url") or "")),
        ("uin", identity.get("uin", "")),
        ("key", identity.get("key", "")),
        ("pass_ticket", identity.get("pass_ticket", "")),
        ("wxtoken", identity.get("wxtoken", "") or "777"),
        ("devicetype", identity.get("devicetype", "")),
        ("clientversion", identity.get("clientversion", "")),
        ("appmsg_token", identity.get("appmsg_token", "")),
        ("x5", identity.get("x5", "") or "0"),
        ("f", "json"),
    ]
    compact = [(key, value) for key, value in params if value not in ("", None)]
    for reply_id in filter_reply_ids:
        compact.append(("filter_reply_list", str(reply_id)))
    required = {"appmsgid", "idx", "comment_id", "content_id", "id"}
    if not required.issubset({key for key, value in compact if value}):
        return ""
    parsed = urlparse(article_url)
    return urlunparse((parsed.scheme or "https", parsed.netloc or "mp.weixin.qq.com", "/mp/appmsg_comment", "", urlencode(compact, doseq=True), ""))


def fetch_all_comment_replies(
    *,
    article_url: str,
    html_text: str,
    request_headers: dict[str, Any],
    merged_comments: dict[str, Any],
    headers: dict[str, str],
    http_get: HttpGetCallable,
    reply_limit: int,
    reply_max_pages_per_comment: int,
    timeout_seconds: float,
    max_body_chars: int,
    reply_page_pause_seconds: float,
) -> dict[str, Any]:
    comments = collect_raw_comment_items(merged_comments)
    targets = [item for item in comments if reply_missing_count(item) > 0]
    manifest: list[dict[str, Any]] = []
    started_at = time.time()
    for index, comment in enumerate(targets, start=1):
        result = fetch_replies_for_comment(
            article_url=article_url,
            html_text=html_text,
            request_headers=request_headers,
            comment=comment,
            headers=headers,
            http_get=http_get,
            reply_limit=reply_limit,
            reply_max_pages_per_comment=reply_max_pages_per_comment,
            timeout_seconds=timeout_seconds,
            max_body_chars=max_body_chars,
        )
        manifest.append(result)
        if reply_page_pause_seconds > 0:
            time.sleep(max(0.0, float(reply_page_pause_seconds)))
    return {
        "attempted": True,
        "ok": all(item.get("ok") for item in manifest) if manifest else True,
        "target_comment_count": len(targets),
        "reply_page_count": sum(int(item.get("page_count") or 0) for item in manifest),
        "reply_added_count": sum(int(item.get("added_count") or 0) for item in manifest),
        "elapsed_seconds": round(time.time() - started_at, 3),
        "targets": manifest,
    }


def fetch_replies_for_comment(
    *,
    article_url: str,
    html_text: str,
    request_headers: dict[str, Any],
    comment: dict[str, Any],
    headers: dict[str, str],
    http_get: HttpGetCallable,
    reply_limit: int,
    reply_max_pages_per_comment: int,
    timeout_seconds: float,
    max_body_chars: int,
) -> dict[str, Any]:
    reply_new = ensure_reply_new(comment)
    total_expected = safe_int(reply_new.get("reply_total_cnt", comment.get("reply_total_cnt")), len(as_reply_list(reply_new.get("reply_list"))))
    max_pages = max(0, int(reply_max_pages_per_comment or 0))
    limit = max(1, int(reply_limit or DEFAULT_REPLY_LIMIT))
    offset = safe_int(reply_new.get("offset"), len(as_reply_list(reply_new.get("reply_list"))))
    buffer = str(reply_new.get("buffer") or "")
    max_reply_id = str(reply_new.get("max_reply_id") or "")
    filter_reply_ids = reply_ids(as_reply_list(reply_new.get("reply_list")))
    page_index = 0
    added_total = 0
    stop_reason = "not_started"

    while True:
        current_replies = unique_replies(as_reply_list(reply_new.get("reply_list")))
        reply_new["reply_list"] = current_replies
        if max_pages and page_index >= max_pages:
            stop_reason = "max_pages_reached"
            break
        if total_expected and len(current_replies) >= total_expected:
            stop_reason = "reply_total_reached"
            break

        request_limit = 20 if total_expected and total_expected - len(current_replies) <= 15 else limit
        reply_url = build_comment_reply_url(
            article_url,
            html_text,
            request_headers,
            comment,
            limit=request_limit,
            offset=offset,
            buffer=buffer,
            max_reply_id=max_reply_id,
            filter_reply_ids=filter_reply_ids,
        )
        if not reply_url:
            stop_reason = "cannot_build_reply_url"
            break

        page = request_json(
            reply_url,
            headers=headers,
            timeout_seconds=timeout_seconds,
            max_body_chars=max_body_chars,
            http_get=http_get,
        )
        parsed = page.get("json")
        if not page.get("ok") or not isinstance(parsed, dict):
            stop_reason = "reply_page_fetch_failed"
            break

        reply_payload = parsed.get("reply_list") if isinstance(parsed.get("reply_list"), dict) else {}
        fetched_replies = as_reply_list(reply_payload.get("reply_list"))
        before_count = len(unique_replies(as_reply_list(reply_new.get("reply_list"))))
        merged_replies = merge_replies(as_reply_list(reply_new.get("reply_list")), fetched_replies)
        after_count = len(merged_replies)
        added_count = max(after_count - before_count, 0)
        added_total += added_count
        reply_new["reply_list"] = merged_replies
        filter_reply_ids = reply_ids(merged_replies)
        if parsed.get("buffer") not in (None, ""):
            buffer = str(parsed.get("buffer") or "")
            reply_new["buffer"] = buffer
        if reply_payload.get("max_reply_id") not in (None, ""):
            max_reply_id = str(reply_payload.get("max_reply_id") or "")
            reply_new["max_reply_id"] = max_reply_id
        offset += added_count
        reply_new["offset"] = offset
        reply_new["has_no_more"] = bool(added_count <= 0 or safe_bool(parsed.get("continue_flag")) is False)

        if added_count <= 0:
            stop_reason = "no_new_replies"
            break
        if total_expected and after_count >= total_expected:
            stop_reason = "reply_total_reached"
            break
        if safe_bool(parsed.get("continue_flag")) is False:
            stop_reason = "continue_flag_false"
            break
        page_index += 1

    final_count = len(unique_replies(as_reply_list(reply_new.get("reply_list"))))
    return {
        "ok": bool(final_count >= total_expected if total_expected else True),
        "comment_id": comment.get("id") or comment.get("comment_id"),
        "content_id": comment.get("content_id"),
        "nickname": comment.get("nick_name") or comment.get("nickname") or "",
        "reply_total_cnt": total_expected,
        "final_reply_count": final_count,
        "added_count": added_total,
        "missing_count": max(total_expected - final_count, 0),
        "page_count": max(0, page_index + (1 if added_total else 0)),
        "stop_reason": stop_reason,
    }


def request_json(
    url: str,
    *,
    headers: dict[str, str],
    timeout_seconds: float,
    max_body_chars: int,
    http_get: HttpGetCallable,
) -> dict[str, Any]:
    try:
        response = http_get(url, headers, normalize_timeout(timeout_seconds))
        status_code = int(getattr(response, "status_code", 0) or 0)
        text = str(getattr(response, "text", "") or "")
        if len(text) > max_body_chars:
            text = text[:max_body_chars]
        parsed = response.json() if hasattr(response, "json") else json.loads(text)
        base_resp = parsed.get("base_resp") if isinstance(parsed, dict) and isinstance(parsed.get("base_resp"), dict) else {}
        ok = 200 <= status_code < 300 and isinstance(parsed, dict) and safe_int(base_resp.get("ret", parsed.get("ret", 0)), 0) == 0
        return {"ok": ok, "status_code": status_code, "json": parsed}
    except Exception as exc:
        return {"ok": False, "status_code": None, "error": str(exc), "json": None}


def requests_get(url: str, headers: dict[str, str], timeout_seconds: float):
    try:
        import requests
    except ModuleNotFoundError as exc:
        raise CommentFetchError("当前 Python 环境缺少 requests，请先安装 requirements.txt 中的依赖") from exc
    return requests.get(url, headers=headers, timeout=normalize_timeout(timeout_seconds))


def normalize_comment_request_headers(headers: dict[str, Any] | None, *, referer: str) -> dict[str, str]:
    """复用微信内置浏览器请求头，只覆盖评论接口必要的 Accept 和 Referer。"""
    normalized = normalize_request_headers(headers)
    allowed = (
        "user-agent",
        "accept-language",
        "cookie",
        "x-requested-with",
        "origin",
        "sec-fetch-site",
        "sec-fetch-mode",
        "sec-fetch-dest",
    )
    result = {key: normalized[key] for key in allowed if key in normalized}
    result.setdefault("user-agent", "Mozilla/5.0 MicroMessenger")
    result.setdefault("accept-language", "zh-CN,zh;q=0.9")
    result["accept"] = "application/json,text/plain,*/*"
    result["referer"] = referer
    return result


def extract_comment_identity(article_url: str, html_text: str, request_headers: dict[str, Any] | None = None) -> dict[str, str]:
    parsed = urlparse(str(article_url or ""))
    query = parse_qs(parsed.query, keep_blank_values=True)
    cookies = cookie_map(header_value(request_headers or {}, "cookie"))
    return {
        "biz": first_query_value(query, "__biz") or extract_js_value(html_text, "biz"),
        "mid": first_query_value(query, "mid") or first_query_value(query, "appmsgid") or extract_js_value(html_text, "mid") or extract_js_value(html_text, "appmsgid"),
        "idx": first_query_value(query, "idx") or extract_js_value(html_text, "idx"),
        "comment_id": extract_js_value(html_text, "comment_id"),
        "uin": first_query_value(query, "uin") or cookies.get("wxuin", ""),
        "key": first_query_value(query, "key"),
        "pass_ticket": first_query_value(query, "pass_ticket") or cookies.get("pass_ticket", ""),
        "wxtoken": first_query_value(query, "wxtoken"),
        "devicetype": first_query_value(query, "devicetype"),
        "clientversion": first_query_value(query, "version") or first_query_value(query, "clientversion"),
        "appmsg_token": first_query_value(query, "appmsg_token") or cookies.get("appmsg_token", "") or extract_js_value(html_text, "appmsg_token"),
        "comment_scene": first_query_value(query, "comment_scene") or extract_js_value(html_text, "comment_scene"),
        "scene": first_query_value(query, "scene") or extract_js_value(html_text, "source"),
        "subscene": first_query_value(query, "subscene"),
        "send_time": first_query_value(query, "send_time") or extract_js_value(html_text, "ct"),
        "x5": first_query_value(query, "x5"),
        "sessionid": first_query_value(query, "sessionid"),
        "enterid": first_query_value(query, "enterid"),
        "ascene": first_query_value(query, "ascene"),
        "lang": first_query_value(query, "lang") or extract_js_value(html_text, "lang"),
        "countrycode": first_query_value(query, "countrycode"),
    }


def merge_comment_pages(pages: list[dict[str, Any]]) -> dict[str, Any]:
    if not pages:
        return {}
    merged = dict(pages[0])
    for key in COMMENT_LIST_KEYS:
        merged[key] = []
    seen_by_key = {key: set() for key in COMMENT_LIST_KEYS}
    for page in pages:
        for key in COMMENT_LIST_KEYS:
            merge_comment_list(merged, page, key, seen_by_key[key])
    last_page = pages[-1]
    for key in ("continue_flag", "total_count", "elected_comment_total_cnt", "reply_flag", "base_resp", "errmsg", "buffer"):
        if key in last_page:
            merged[key] = last_page.get(key)
    merged["merged_page_count"] = len(pages)
    return merged


def extract_structured_comments(data: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    for section, key in comment_sections():
        items = as_dict_list(data.get(key) if isinstance(data, dict) else [])
        for item in items:
            normalized = normalize_comment(item, section, key)
            identity = comment_identity(normalized)
            if identity in seen:
                seen[identity]["source_keys"] = sorted(set(seen[identity].get("source_keys", []) + normalized.get("source_keys", [])))
                if section == "elected":
                    seen[identity]["section"] = "elected"
                    seen[identity]["is_elected"] = True
                continue
            seen[identity] = normalized
            result.append(normalized)
    return result


def normalize_comment(item: dict[str, Any], section: str, source_key: str) -> dict[str, Any]:
    reply_new = item.get("reply_new") if isinstance(item.get("reply_new"), dict) else {}
    replies = [normalize_reply(reply, item) for reply in as_reply_list(reply_new.get("reply_list") or item.get("reply_list"))]
    replies = [reply for reply in unique_replies_raw(replies)]
    ip_wording = normalize_ip_wording(item.get("ip_wording") or {})
    reply_total_count = safe_int(reply_new.get("reply_total_cnt", item.get("reply_total_cnt")), len(replies))
    reply_available_count = len(replies)
    return {
        "level": 1,
        "section": section,
        "source_key": source_key,
        "source_keys": [source_key],
        "id": item.get("id"),
        "comment_id": item.get("comment_id") or item.get("id"),
        "content_id": item.get("content_id"),
        "parent_comment_id": "",
        "reply_id": "",
        "nickname": item.get("nick_name") or item.get("nickname") or "",
        "avatar_url": item.get("logo_url") or item.get("avatar_url") or "",
        "avatar_local_path": item.get("avatar_local_path") or "",
        "openid": item.get("openid") or "",
        "identity_name": item.get("identity_name") or "",
        "identity_type": item.get("identity_type"),
        "content": clean_comment_text(item.get("content") or ""),
        "content_raw": item.get("content") or "",
        "create_time": item.get("create_time"),
        "create_time_text": format_timestamp(item.get("create_time")),
        "like_num": safe_int(item.get("like_num"), 0),
        "like_status": item.get("like_status"),
        "is_elected": bool(item.get("is_elected") or section == "elected"),
        "is_top": item.get("is_top"),
        "location": format_ip_location(ip_wording),
        "ip": ip_wording,
        "reply_total_count": reply_total_count,
        "reply_available_count": reply_available_count,
        "reply_missing_count": max(reply_total_count - reply_available_count, 0),
        "reply_complete": reply_total_count <= reply_available_count,
        "max_reply_id": reply_new.get("max_reply_id") or item.get("max_reply_id"),
        "reply_offset": reply_new.get("offset"),
        "reply_buffer": reply_new.get("buffer"),
        "reply_has_no_more": reply_new.get("has_no_more"),
        "multi_info": item.get("multi_info") if isinstance(item.get("multi_info"), dict) else {},
        "raw_payload": item,
        "replies": replies,
    }


def normalize_reply(reply: dict[str, Any], parent: dict[str, Any]) -> dict[str, Any]:
    ip_wording = normalize_ip_wording(reply.get("ip_wording") or {})
    return {
        "level": 2,
        "section": "reply",
        "source_key": "reply_new.reply_list",
        "id": reply.get("id"),
        "comment_id": "",
        "content_id": "",
        "parent_comment_id": parent.get("comment_id") or parent.get("id") or "",
        "parent_content_id": parent.get("content_id") or "",
        "reply_id": reply.get("reply_id") or reply.get("id"),
        "nickname": reply.get("nick_name") or reply.get("nickname") or "",
        "avatar_url": reply.get("logo_url") or reply.get("avatar_url") or "",
        "avatar_local_path": reply.get("avatar_local_path") or "",
        "openid": reply.get("openid") or "",
        "identity_name": reply.get("identity_name") or "",
        "identity_type": reply.get("identity_type"),
        "content": clean_comment_text(reply.get("content") or ""),
        "content_raw": reply.get("content") or "",
        "create_time": reply.get("create_time"),
        "create_time_text": format_timestamp(reply.get("create_time")),
        "like_num": safe_int(reply.get("reply_like_num", reply.get("like_num")), 0),
        "like_status": reply.get("reply_like_status") or reply.get("like_status"),
        "location": format_ip_location(ip_wording),
        "ip": ip_wording,
        "multi_info": reply.get("multi_info") if isinstance(reply.get("multi_info"), dict) else {},
        "raw_payload": reply,
    }


def download_comment_resources(
    comments: list[dict[str, Any]],
    article_dir: Path,
    *,
    resource_get: HttpGetCallable | None = None,
    download_avatars: bool = True,
    download_emojis: bool = True,
    download_pictures: bool = True,
    timeout_seconds: float = DEFAULT_RESOURCE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    resources: dict[str, Any] = {}
    getter = resource_get or requests_get
    for comment in comments:
        if download_avatars:
            register_comment_resource(
                resources,
                article_dir,
                comment,
                level=1,
                resource_type="avatar",
                getter=getter,
                timeout_seconds=timeout_seconds,
            )
        register_multi_info_resources(
            resources,
            article_dir,
            comment,
            level=1,
            getter=getter,
            download_emojis=download_emojis,
            download_pictures=download_pictures,
            timeout_seconds=timeout_seconds,
        )
        for reply in comment.get("replies") or []:
            if not isinstance(reply, dict):
                continue
            if download_avatars:
                register_comment_resource(
                    resources,
                    article_dir,
                    reply,
                    level=2,
                    resource_type="avatar",
                    getter=getter,
                    timeout_seconds=timeout_seconds,
                )
            register_multi_info_resources(
                resources,
                article_dir,
                reply,
                level=2,
                getter=getter,
                download_emojis=download_emojis,
                download_pictures=download_pictures,
                timeout_seconds=timeout_seconds,
            )
    return {"attempted": True, "resources": resources, "counts": count_comment_resources(resources)}


def register_multi_info_resources(
    resources: dict[str, Any],
    article_dir: Path,
    item: dict[str, Any],
    *,
    level: int,
    getter: HttpGetCallable,
    download_emojis: bool = True,
    download_pictures: bool = True,
    timeout_seconds: float = DEFAULT_RESOURCE_TIMEOUT_SECONDS,
) -> None:
    multi_info = item.get("multi_info") if isinstance(item.get("multi_info"), dict) else {}
    if download_emojis:
        for emoji in multi_info.get("emojis") or []:
            if isinstance(emoji, dict):
                register_comment_resource(
                    resources,
                    article_dir,
                    item,
                    level=level,
                    resource_type="emoji",
                    getter=getter,
                    url=first_non_empty(emoji, ("url", "cdn_url", "thumb_url", "emoji_url")),
                    target_item=emoji,
                    timeout_seconds=timeout_seconds,
                )
    if download_pictures:
        for picture in multi_info.get("pictures") or []:
            if isinstance(picture, dict):
                register_comment_resource(
                    resources,
                    article_dir,
                    item,
                    level=level,
                    resource_type="picture",
                    getter=getter,
                    url=first_non_empty(picture, ("url", "cdn_url", "thumb_url", "pic_url")),
                    target_item=picture,
                    timeout_seconds=timeout_seconds,
                )


def register_comment_resource(
    resources: dict[str, Any],
    article_dir: Path,
    item: dict[str, Any],
    *,
    level: int,
    resource_type: str,
    getter: HttpGetCallable,
    url: str = "",
    target_item: dict[str, Any] | None = None,
    timeout_seconds: float = DEFAULT_RESOURCE_TIMEOUT_SECONDS,
) -> None:
    raw_url = url or str(item.get("avatar_url") or "")
    if not raw_url:
        return
    used_by = {
        "level": level,
        "comment_id": str(item.get("comment_id") or item.get("parent_comment_id") or ""),
        "content_id": str(item.get("content_id") or item.get("parent_content_id") or ""),
        "reply_id": str(item.get("reply_id") or ""),
        "nickname": item.get("nickname") or "",
    }
    if raw_url in resources:
        resources[raw_url].setdefault("used_by", []).append(used_by)
        apply_comment_resource_result(item, resource_type, resources[raw_url], target_item=target_item)
        return
    downloaded = download_comment_resource(raw_url, article_dir, resource_type, getter=getter, timeout_seconds=timeout_seconds)
    downloaded["used_by"] = [used_by]
    resources[raw_url] = downloaded
    apply_comment_resource_result(item, resource_type, downloaded, target_item=target_item)


def apply_comment_resource_result(
    item: dict[str, Any],
    resource_type: str,
    resource: dict[str, Any],
    *,
    target_item: dict[str, Any] | None = None,
) -> None:
    if resource_type == "avatar" and resource.get("local_path"):
        item["avatar_local_path"] = resource["local_path"]
    if target_item is None:
        return
    target_item["download_ok"] = bool(resource.get("ok"))
    if resource.get("local_path"):
        target_item["local_path"] = resource["local_path"]
    if resource.get("error"):
        target_item["download_error"] = resource["error"]
    if resource.get("content_type"):
        target_item["content_type"] = resource["content_type"]
    if resource.get("byte_length") is not None:
        target_item["byte_length"] = resource["byte_length"]


def download_comment_resource(
    url: str,
    article_dir: Path,
    resource_type: str,
    *,
    getter: HttpGetCallable,
    timeout_seconds: float = DEFAULT_RESOURCE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    subdir = {"avatar": "avatar", "emoji": "emoji", "picture": "picture"}.get(resource_type, "other")
    target_dir = article_dir / "comments_img" / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        response = getter(url, dict(RESOURCE_HEADERS), normalize_timeout(timeout_seconds))
        status_code = int(getattr(response, "status_code", 0) or 0)
        content = bytes(getattr(response, "content", b"") or b"")
        headers = getattr(response, "headers", {}) or {}
        content_type = header_value(headers, "content-type")
        if status_code < 200 or status_code >= 300:
            return {"ok": False, "type": resource_type, "url_redacted": redact_sensitive_url(url), "error": f"HTTP {status_code}"}
        if len(content) > MAX_RESOURCE_BYTES:
            return {"ok": False, "type": resource_type, "url_redacted": redact_sensitive_url(url), "error": "image_too_large"}
    except Exception as exc:
        return {"ok": False, "type": resource_type, "url_redacted": redact_sensitive_url(url), "error": str(exc)}

    suffix = comment_resource_suffix(url, content_type)
    filename = f"{hashlib.sha1(url.encode('utf-8', errors='ignore')).hexdigest()[:16]}{suffix}"
    target_path = target_dir / filename
    target_path.write_bytes(content)
    return {
        "ok": True,
        "type": resource_type,
        "url_redacted": redact_sensitive_url(url),
        "local_path": f"comments_img/{subdir}/{filename}",
        "content_type": content_type,
        "byte_length": len(content),
    }


def build_comment_summary(
    data: dict[str, Any],
    comments: list[dict[str, Any]],
    *,
    page_summaries: list[dict[str, Any]],
    pagination_complete: bool,
    stop_reason: str,
    continue_flag_final: bool | None,
    reply_fetch: dict[str, Any],
    resource_result: dict[str, Any],
) -> dict[str, Any]:
    reply_count = sum(len(item.get("replies", [])) for item in comments)
    reply_total_count = sum(safe_int(item.get("reply_total_count"), len(item.get("replies", []))) for item in comments)
    reply_missing = sum(max(safe_int(item.get("reply_total_count"), 0) - len(item.get("replies", [])), 0) for item in comments)
    top_level_count = len(comments)
    return {
        "top_level_comment_count": top_level_count,
        "reply_count": reply_count,
        "total_message_count": top_level_count + reply_count,
        "total_count_from_api": data.get("total_count") if isinstance(data, dict) else None,
        "elected_comment_total_cnt": data.get("elected_comment_total_cnt") if isinstance(data, dict) else None,
        "continue_flag": data.get("continue_flag") if isinstance(data, dict) else None,
        "continue_flag_final": continue_flag_final,
        "pagination_complete": pagination_complete,
        "stop_reason": stop_reason,
        "page_count": len(page_summaries),
        "page_summaries": page_summaries,
        "reply_total_count_from_api": reply_total_count,
        "reply_missing_count": reply_missing,
        "reply_fetch": {key: value for key, value in reply_fetch.items() if key != "targets"},
        "resource_counts": resource_result.get("counts", {}),
    }


def comment_sections() -> tuple[tuple[str, str], ...]:
    return (
        ("normal", "comment"),
        ("normal", "comment_list"),
        ("elected", "elected_comment"),
        ("elected", "elected_comment_list"),
        ("friend", "friend_comment"),
        ("mine", "my_comment"),
    )


def collect_raw_comment_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in COMMENT_LIST_KEYS:
        for item in as_dict_list(data.get(key)):
            identity = raw_comment_identity(item)
            if identity in seen:
                continue
            seen.add(identity)
            comments.append(item)
    return comments


def merge_comment_list(target: dict[str, Any], source: dict[str, Any], key: str, seen: set[str]) -> None:
    target_items = target.setdefault(key, [])
    if not isinstance(target_items, list):
        target_items = []
        target[key] = target_items
    for item in as_dict_list(source.get(key)):
        identity = raw_comment_identity(item)
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        target_items.append(item)


def count_new_comment_items(data: Any, seen: set[str]) -> int:
    if not isinstance(data, dict):
        return 0
    count = 0
    for key in COMMENT_LIST_KEYS:
        for item in as_dict_list(data.get(key)):
            identity = f"{key}:{raw_comment_identity(item)}"
            if identity in seen:
                continue
            seen.add(identity)
            count += 1
    return count


def ensure_reply_new(comment: dict[str, Any]) -> dict[str, Any]:
    reply_new = comment.get("reply_new")
    if not isinstance(reply_new, dict):
        reply_new = {}
        comment["reply_new"] = reply_new
    if not isinstance(reply_new.get("reply_list"), list):
        reply_new["reply_list"] = as_reply_list(reply_new.get("reply_list"))
    return reply_new


def reply_missing_count(comment: dict[str, Any]) -> int:
    reply_new = ensure_reply_new(comment)
    replies = unique_replies(as_reply_list(reply_new.get("reply_list")))
    total = safe_int(reply_new.get("reply_total_cnt", comment.get("reply_total_cnt")), len(replies))
    return max(total - len(replies), 0)


def as_dict_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def as_reply_list(value: Any) -> list[dict[str, Any]]:
    return as_dict_list(value)


def reply_ids(replies: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for reply in replies:
        value = reply.get("reply_id") or reply.get("id")
        if value in (None, ""):
            continue
        text = str(value)
        if text not in result:
            result.append(text)
    return result


def merge_replies(existing: list[dict[str, Any]], fetched: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = unique_replies([*existing, *fetched])
    if all(str(item.get("reply_id") or item.get("id") or "").isdigit() for item in merged):
        return sorted(merged, key=lambda item: int(str(item.get("reply_id") or item.get("id") or 0)))
    return merged


def unique_replies(replies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for reply in replies:
        identity = str(reply.get("reply_id") or reply.get("id") or json.dumps(reply, ensure_ascii=False, default=str))
        if identity in seen:
            continue
        seen.add(identity)
        result.append(reply)
    return result


def unique_replies_raw(replies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return unique_replies(replies)


def comment_identity(comment: dict[str, Any]) -> str:
    return str(comment.get("content_id") or comment.get("comment_id") or comment.get("id") or json.dumps(comment, ensure_ascii=False, default=str))


def raw_comment_identity(item: dict[str, Any]) -> str:
    return str(item.get("content_id") or item.get("id") or item.get("comment_id") or json.dumps(item, ensure_ascii=False, default=str))


def clean_comment_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def format_timestamp(value: Any) -> str:
    if value in (None, ""):
        return ""
    text = str(value)
    if not re.fullmatch(r"\d{9,12}", text):
        return text
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(text)))
    except (OSError, ValueError):
        return text


def normalize_ip_wording(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "country_name": value.get("country_name") or value.get("countryName") or "",
        "province_name": value.get("province_name") or value.get("provinceName") or "",
        "city_name": value.get("city_name") or value.get("cityName") or "",
    }


def format_ip_location(ip_wording: dict[str, Any]) -> str:
    for key in ("city_name", "province_name", "country_name"):
        value = str(ip_wording.get(key) or "").strip()
        if value:
            return value
    return ""


def safe_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if text in {"0", "false", "no"}:
        return False
    if text in {"1", "true", "yes"}:
        return True
    return None


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_timeout(value: Any) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS
    if seconds <= 0:
        return DEFAULT_TIMEOUT_SECONDS
    return DEFAULT_TIMEOUT_SECONDS if seconds > 30 else seconds


def extract_js_value(text: str, name: str) -> str:
    source = str(text or "")
    string_pattern = rf"(?:var\s+|window\.)?{re.escape(name)}\s*=\s*(['\"])(?P<value>.*?)(?<!\\)\1"
    match = re.search(string_pattern, source)
    if match:
        return html.unescape(match.group("value").replace("\\/", "/").replace("\\x26", "&").replace("\\u0026", "&"))
    number_pattern = rf"(?:var\s+|window\.)?{re.escape(name)}\s*=\s*(?P<value>-?\d+(?:\.\d+)?)(?:\s*[;,])"
    number_match = re.search(number_pattern, source)
    return number_match.group("value") if number_match else ""


def first_query_value(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key) or []
    return str(values[0]) if values else ""


def header_value(headers: Any, name: str) -> str:
    target = name.lower()
    for key, value in dict(headers or {}).items():
        if str(key).lower() == target:
            return str(value)
    return ""


def cookie_map(cookie_header: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in str(cookie_header or "").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def first_non_empty(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = data.get(key)
        if value:
            return str(value)
    return ""


def comment_resource_suffix(url: str, content_type: str) -> str:
    lowered = str(content_type or "").lower()
    for marker, suffix in (
        ("png", ".png"),
        ("gif", ".gif"),
        ("webp", ".webp"),
        ("svg", ".svg"),
        ("jpeg", ".jpg"),
        ("jpg", ".jpg"),
    ):
        if marker in lowered:
            return suffix
    path_suffix = Path(urlparse(str(url or "")).path).suffix.lower()
    if path_suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif"}:
        return path_suffix
    guessed = mimetypes.guess_extension(content_type.split(";")[0].strip()) if content_type else ""
    return guessed or ".jpg"


def count_comment_resources(resources: dict[str, Any]) -> dict[str, int]:
    counts = empty_resource_counts()
    for item in resources.values():
        if not item.get("ok"):
            counts["failed"] += 1
            continue
        resource_type = str(item.get("type") or "other")
        counts[resource_type if resource_type in counts else "other"] += 1
    return counts


def empty_resource_counts() -> dict[str, int]:
    return {"avatar": 0, "emoji": 0, "picture": 0, "other": 0, "failed": 0}


def current_time_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
