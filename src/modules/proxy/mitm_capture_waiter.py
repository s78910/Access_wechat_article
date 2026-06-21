from __future__ import annotations

import html
import json
import queue
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from src.core.config import LOG_DIR
from src.modules.detail.account_identity import is_valid_account_name_text, normalize_account_name_text
from src.modules.storage.article_archive_store import (
    first_valid_account_name,
    first_valid_wechat_article_short_link,
    normalize_published_article_time,
)
from src.modules.utils.url_utils import redact_url as _redact_url

DEFAULT_MITM_CAPTURE_TIMEOUT_SECONDS = 10.0
LONG_WAIT_TIMEOUT_THRESHOLD_SECONDS = 30.0
WECHAT_ARTICLE_HOST = "mp.weixin.qq.com"
GENERIC_ARTICLE_TITLE_PATTERN = re.compile(r"^\u7b2c\s*\d+\s*\u7bc7\u6587\u7ae0")
EARLY_REFERER_FALLBACK_TITLE_REASONS = {
    "wechat_response_target_title_seen",
    "wechat_response_title_candidate",
    "article_html_without_key_ignored",
}


def is_generic_article_title(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text and GENERIC_ARTICLE_TITLE_PATTERN.fullmatch(text))

def resolve_failure_article_title(report: dict[str, Any], target_title: str, article_index: int) -> str:
    """失败日志只展示真实标题；没有识别到标题时不再使用“第 N 篇文章”占位。"""
    storage = report.get("storage") if isinstance(report.get("storage"), dict) else {}
    raw_detail = report.get("article_detail") if isinstance(report.get("article_detail"), dict) else {}
    target_article = report.get("target_article") if isinstance(report.get("target_article"), dict) else {}
    candidates = [
        target_title,
        storage.get("title"),
        raw_detail.get("article_title"),
        raw_detail.get("title"),
        target_article.get("title"),
    ]
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text and not is_generic_article_title(text):
            return text
    return "未识别标题"

def resolve_capture_failure_reason(report: dict[str, Any]) -> str:
    fallback = report.get("fallback_capture") if isinstance(report.get("fallback_capture"), dict) else {}
    return str(
        report.get("automation_error")
        or fallback.get("error")
        or fallback.get("reason")
        or report.get("conclusion")
        or "未捕获到可保存的文章主 HTML"
    )

def is_report_ready_for_article_storage(report: dict[str, Any]) -> bool:
    """只有确实拿到文章主 HTML 时才进入本地归档和数据库保存。"""
    if report.get("automation_error"):
        return False

    main_capture = report.get("main_html_capture") if isinstance(report.get("main_html_capture"), dict) else {}
    source_html_path = Path(str(main_capture.get("private_html_path") or ""))
    try:
        if source_html_path.is_file() and source_html_path.stat().st_size > 0:
            return True
    except OSError:
        pass

    raw_detail = report.get("article_detail") if isinstance(report.get("article_detail"), dict) else {}
    html_text = str(raw_detail.get("html_text") or "").strip()
    if html_text:
        return True

    source = str(main_capture.get("source") or "")
    return bool(source in {"mitm_referer_fallback", "mitm_keyed_url_fallback"} and str(main_capture.get("url") or "").strip())

def get_main_html_capture_source(report: dict[str, Any]) -> str:
    main_capture = report.get("main_html_capture") if isinstance(report.get("main_html_capture"), dict) else {}
    return str(main_capture.get("source") or "").strip()

def build_capture_ready_message(report: dict[str, Any]) -> str:
    """按采集来源区分日志文案，避免把 Referer 保底误解为 MITM 已解密主响应。"""
    source = get_main_html_capture_source(report)
    if source == "mitm":
        return "MITM 已捕获带 key 请求的 response HTML，将直接解析文章详情"
    if source == "mitm_keyed_url_fallback":
        return "MITM 已发现带 key 文章 URL，已进入 requests 保底采集"
    if source == "mitm_referer_fallback":
        return "MITM 在 Referer 中发现带 key URL，已进入 requests 保底采集"
    return "已获取可归档的文章详情输入"

def _extract_article_title_from_html(html_text: str) -> str:
    if not html_text:
        return ""
    patterns = (
        r"var\s+msg_title\s*=\s*['\"](?P<value>.*?)['\"]",
        r"(?i)<meta[^>]+property=['\"]og:title['\"][^>]+content=['\"](?P<value>.*?)['\"]",
        r"(?i)<meta[^>]+name=['\"]twitter:title['\"][^>]+content=['\"](?P<value>.*?)['\"]",
        r"(?is)<title[^>]*>(?P<value>.*?)</title>",
    )
    for pattern in patterns:
        match = re.search(pattern, html_text)
        if not match:
            continue
        value = html.unescape(match.group("value"))
        value = re.sub(r"\s+", " ", value).strip()
        if value:
            return value
    return ""

def extract_account_name_from_html_text(html_text: str) -> str:
    """从微信文章 HTML 中提取公众号名称，作为主页窗口读取失败时的兜底来源。"""
    text = str(html_text or "")
    patterns = (
        r"var\s+nickname\s*=\s*['\"](?P<value>.*?)['\"]",
        r"\bnickname\s*:\s*['\"](?P<value>.*?)['\"]",
        r"var\s+profile_nickname\s*=\s*['\"](?P<value>.*?)['\"]",
        r"\bprofile_nickname\s*:\s*['\"](?P<value>.*?)['\"]",
        r"(?is)<[^>]+id=['\"]js_name['\"][^>]*>(?P<value>.*?)</[^>]+>",
        r"var\s+user_name\s*=\s*['\"](?P<value>.*?)['\"]",
        r"(?i)<meta[^>]+property=['\"]og:article:author['\"][^>]+content=['\"](?P<value>.*?)['\"]",
        r"(?i)<meta[^>]+name=['\"]author['\"][^>]+content=['\"](?P<value>.*?)['\"]",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        value = re.sub(r"<[^>]+>", "", match.group("value"))
        value = re.sub(r"\s+", " ", normalize_account_name_text(value)).strip()
        if is_valid_account_name_text(value):
            return value
    return ""

def extract_publish_time_from_html_text(html_text: str) -> str:
    """从文章 HTML 中提取页面展示的发布时间，统一保持到分钟级。"""
    text = str(html_text or "")
    timestamp_match = re.search(r"var\s+ct\s*=\s*['\"](?P<value>\d{8,})['\"]", text)
    if timestamp_match:
        return normalize_published_article_time(timestamp_match.group("value"))

    text_match = re.search(r"var\s+publish_time\s*=\s*['\"](?P<value>[^'\"]+)['\"]", text)
    if text_match:
        return normalize_published_article_time(text_match.group("value"))
    return ""

def collect_article_capture_report_from_mitm(
    capture_event_queue,
    config: dict | None,
    *,
    article_index: int,
    timeout_seconds: float = DEFAULT_MITM_CAPTURE_TIMEOUT_SECONDS,
    idle_refresh_seconds: float | None = None,
    idle_callback=None,
    min_event_timestamp: float | None = None,
    target_title: str = "",
) -> dict[str, Any]:
    """等待常驻 MITM 发来的文章主 HTML 事件，并转换成当前归档流程使用的 report。

    idle_refresh_seconds / idle_callback 仅为兼容旧调用保留。
    当前采集策略要求一次点击只等待 MITM 捕获，不主动刷新微信文章窗口，避免重复请求带 key 的 URL。
    """
    config = config or {}
    if capture_event_queue is None:
        return build_mitm_wait_failed_report(config, article_index, "MITM 捕获事件队列未初始化")

    wait_seconds = resolve_mitm_capture_timeout_seconds(config, timeout_seconds)
    start_time = time.time()
    deadline = start_time + max(0.01, wait_seconds)
    mitm_diagnostics: list[dict[str, Any]] = []
    while True:
        now = time.time()
        remaining = max(0.0, deadline - now)
        if remaining <= 0:
            if mitm_diagnostics:
                fallback_report = build_referer_fallback_report_from_mitm_diagnostics(
                    config,
                    article_index,
                    mitm_diagnostics,
                    target_title=target_title,
                )
                if fallback_report:
                    return fallback_report
                reason = build_mitm_timeout_reason("等待 MITM 捕获文章主 HTML 超时", mitm_diagnostics)
                return build_mitm_wait_failed_report(
                    config,
                    article_index,
                    reason,
                    mitm_diagnostics=mitm_diagnostics,
                )
            reason = (
                "等待 MITM 捕获文章主 HTML 超时；MITM 未看到文章主页面请求，"
                "流量可能没有进入当前代理、微信内置浏览器复用了缓存，或文章窗口未触发网络请求"
            )
            return build_mitm_wait_failed_report(config, article_index, reason)

        wait_timeout = min(0.2, remaining)
        try:
            event = capture_event_queue.get(timeout=wait_timeout)
        except queue.Empty:
            continue
        except Exception as exc:
            if mitm_diagnostics:
                reason = build_mitm_timeout_reason(f"读取 MITM 捕获事件失败：{exc}", mitm_diagnostics)
                return build_mitm_wait_failed_report(
                    config,
                    article_index,
                    reason,
                    mitm_diagnostics=mitm_diagnostics,
                )
            return build_mitm_wait_failed_report(config, article_index, f"读取 MITM 捕获事件失败：{exc}")

        if is_stale_mitm_event(event, min_event_timestamp):
            continue
        if isinstance(event, dict) and event.get("type") == "article_main_html_captured":
            return article_capture_report_from_mitm_event(event, config, article_index=article_index)
        if isinstance(event, dict) and event.get("type") == "article_main_html_requested":
            append_mitm_diagnostic(mitm_diagnostics, event, target_title=target_title)
            fallback_report = build_keyed_url_fallback_report_from_mitm_diagnostics(
                config,
                article_index,
                mitm_diagnostics,
                target_title=target_title,
            )
            if fallback_report:
                return fallback_report
            fallback_report = build_confirmed_referer_fallback_report_from_mitm_diagnostics(
                config,
                article_index,
                mitm_diagnostics,
                target_title=target_title,
            )
            if fallback_report:
                return fallback_report
            continue
        if isinstance(event, dict) and event.get("type") == "article_main_html_candidate":
            append_mitm_diagnostic(mitm_diagnostics, event, target_title=target_title)
            fallback_report = build_confirmed_referer_fallback_report_from_mitm_diagnostics(
                config,
                article_index,
                mitm_diagnostics,
                target_title=target_title,
            )
            if fallback_report:
                return fallback_report
            continue

def drain_capture_event_queue(capture_event_queue) -> int:
    """开始新文章前清理历史 MITM 捕获事件，防止旧页面响应污染本次任务。"""
    if capture_event_queue is None:
        return 0

    removed = 0
    while True:
        try:
            capture_event_queue.get_nowait()
        except queue.Empty:
            break
        except Exception:
            break
        removed += 1
    return removed

def is_stale_mitm_event(event: Any, min_event_timestamp: float | None) -> bool:
    """忽略点击前产生的 MITM 事件，避免关闭旧文章窗口时的 Referer 抢跑污染本轮。"""
    if min_event_timestamp is None or not isinstance(event, dict):
        return False
    try:
        event_timestamp = float(event.get("timestamp") or 0)
    except (TypeError, ValueError):
        return False
    return bool(event_timestamp and event_timestamp < float(min_event_timestamp))

def append_mitm_diagnostic(
    diagnostics: list[dict[str, Any]],
    event: dict[str, Any],
    max_items: int = 80,
    *,
    target_title: str = "",
) -> None:
    event_title = str(event.get("title") or "").strip()
    title_candidates = [
        str(item or "").strip()
        for item in (event.get("title_candidates") or [])
        if str(item or "").strip()
    ]
    comparable_target_title = normalize_compare_text(target_title)
    title_matches_target = bool(
        comparable_target_title
        and any(
            normalize_compare_text(candidate) == comparable_target_title
            for candidate in [event_title, *title_candidates]
            if str(candidate or "").strip()
        )
    )
    safe_event = {
        "reason": event.get("reason") or event.get("type"),
        "url": event.get("url"),
        "url_redacted": event.get("url_redacted"),
        "host": event.get("host"),
        "path": event.get("path"),
        "method": event.get("method"),
        "query": event.get("query") if isinstance(event.get("query"), dict) else {},
        "query_keys": list(event.get("query_keys") or []),
        "request_headers": dict(event.get("request_headers") or {}) if isinstance(event.get("request_headers"), dict) else {},
        "url_source": event.get("url_source"),
        "carrier_url_redacted": event.get("carrier_url_redacted"),
        "status_code": event.get("status_code"),
        "content_type": event.get("content_type"),
        "body_chars": event.get("body_chars"),
        "error": event.get("error"),
        "title": event_title,
        "title_candidates": title_candidates[:5],
        "title_matched": event.get("title_matched"),
        "runtime_params": event.get("runtime_params") if isinstance(event.get("runtime_params"), dict) else {},
        "target_title": str(target_title or "").strip(),
        "title_matches_target": title_matches_target,
        "createdAt": event.get("createdAt"),
    }
    diagnostics.append(safe_event)
    del diagnostics[:-max(1, int(max_items))]

def build_referer_fallback_report_from_mitm_diagnostics(
    config: dict[str, Any],
    article_index: int,
    diagnostics: list[dict[str, Any]],
    *,
    target_title: str = "",
) -> dict[str, Any]:
    """只有 key URL 来自 Referer 时才构造 requests 保底 report，避免重复重放真实主请求。"""
    return build_keyed_url_fallback_report_from_mitm_diagnostics(
        config,
        article_index,
        diagnostics,
        target_title=target_title,
        allowed_url_sources={"referer"},
        fallback_source="mitm_referer_fallback",
        fallback_message="MITM 只在 Referer 中看到带 key 的文章 URL，已进入 requests 保底获取文章详情",
    )

def build_keyed_url_fallback_report_from_mitm_diagnostics(
    config: dict[str, Any],
    article_index: int,
    diagnostics: list[dict[str, Any]],
    *,
    target_title: str = "",
    allowed_url_sources: set[str] | None = None,
    fallback_source: str = "mitm_keyed_url_fallback",
    fallback_message: str = "MITM 已看到带 key 的文章 URL，已进入 requests 保底获取文章详情",
) -> dict[str, Any]:
    """只要已经看到带 key 的文章 URL，就可模拟请求详情；归档阶段再用标题校验防串台。"""
    for item in reversed([value for value in diagnostics if isinstance(value, dict)]):
        if item.get("reason") != "article_main_html_requested":
            continue
        url_source = str(item.get("url_source") or "request").lower()
        if allowed_url_sources is not None and url_source not in allowed_url_sources:
            continue
        keyed_url = str(item.get("url") or "").strip()
        if not keyed_url:
            continue
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        title = str(target_title or item.get("target_title") or f"第 {article_index} 篇文章").strip()
        source_label = "mitm_referer_fallback" if url_source == "referer" else fallback_source
        message = (
            "MITM 只在 Referer 中看到带 key 的文章 URL，已进入 requests 保底获取文章详情"
            if url_source == "referer"
            else fallback_message
        )
        return {
            "created_at": created_at,
            "target_article": {"title": title},
            "main_html_capture": {
                "url": keyed_url,
                "url_redacted": str(item.get("url_redacted") or _redact_url(keyed_url)),
                "request_headers": dict(item.get("request_headers") or {}),
                "captured_time": created_at,
                "source": source_label,
                "url_source": url_source,
                "carrier_url_redacted": str(item.get("carrier_url_redacted") or ""),
            },
            "storage": {
                "account_name": first_valid_account_name(config.get("account_name")),
                "title": title,
                "article_url_redacted": str(item.get("url_redacted") or _redact_url(keyed_url)),
            },
            "article_detail": {},
            "comment_fetch": {},
            "mitm_diagnostics": list(diagnostics),
            "fallback_capture": {
                "reason": f"keyed_url_from_{url_source}",
                "message": message,
            },
        }
    return {}

def build_confirmed_referer_fallback_report_from_mitm_diagnostics(
    config: dict[str, Any],
    article_index: int,
    diagnostics: list[dict[str, Any]],
    *,
    target_title: str = "",
) -> dict[str, Any]:
    if not has_confirmed_target_title_diagnostic(diagnostics, target_title=target_title):
        return {}
    return build_referer_fallback_report_from_mitm_diagnostics(
        config,
        article_index,
        diagnostics,
        target_title=target_title,
    )

def has_confirmed_target_title_diagnostic(
    diagnostics: list[dict[str, Any]],
    *,
    target_title: str = "",
) -> bool:
    comparable_target_title = normalize_compare_text(target_title)
    if not comparable_target_title:
        return False

    for item in diagnostics:
        if not isinstance(item, dict):
            continue
        if item.get("reason") not in EARLY_REFERER_FALLBACK_TITLE_REASONS:
            continue
        if item.get("title_matches_target") is True:
            return True
        title_values = [
            item.get("title"),
            *(item.get("title_candidates") or []),
        ]
        if any(normalize_compare_text(value) == comparable_target_title for value in title_values):
            return True
    return False

def normalize_compare_text(value: Any) -> str:
    """把标题压缩成可比较文本，避免空格、零宽字符影响同标题判断。"""
    text = str(value or "").replace("\u200b", "").strip().lower()
    return re.sub(r"\s+", "", text)

def resolve_mitm_capture_timeout_seconds(config: dict | None, configured_value: Any = None) -> float:
    """解析文章主 HTML 捕获等待时间；过长等待统一降到 10 秒，避免任务卡住太久。"""
    data = config if isinstance(config, dict) else {}
    raw_value = configured_value if configured_value is not None else data.get("mitm_capture_timeout_seconds")
    if raw_value is None:
        return DEFAULT_MITM_CAPTURE_TIMEOUT_SECONDS

    try:
        seconds = float(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_MITM_CAPTURE_TIMEOUT_SECONDS

    if seconds <= 0:
        return DEFAULT_MITM_CAPTURE_TIMEOUT_SECONDS
    if seconds > LONG_WAIT_TIMEOUT_THRESHOLD_SECONDS:
        return DEFAULT_MITM_CAPTURE_TIMEOUT_SECONDS
    return seconds

def build_mitm_timeout_reason(base_reason: str, diagnostics: list[dict[str, Any]]) -> str:
    if not diagnostics:
        return base_reason
    latest = select_mitm_timeout_diagnostic(diagnostics)
    if latest.get("reason") in {"tls_client_failed", "tls_server_failed"}:
        return (
            f"{base_reason}；MITM 已看到微信 HTTPS 隧道，但 TLS 解密失败，"
            "通常表示微信内置浏览器不信任 mitmproxy CA 证书、证书链异常，或连接被客户端拒绝；"
            f"error={latest.get('error') or '未提供错误详情'}, "
            f"url={latest.get('url_redacted')}"
        )
    if latest.get("reason") in {"wechat_tunnel_error", "mitm_flow_error"}:
        return (
            f"{base_reason}；MITM 微信连接发生错误："
            f"reason={latest.get('reason')}, "
            f"error={latest.get('error') or '未提供错误详情'}, "
            f"url={latest.get('url_redacted')}"
        )
    if latest.get("reason") == "tls_server_established" and not has_matching_tls_client_established(diagnostics, latest):
        return (
            f"{base_reason}；MITM 已连上远端服务器，但客户端侧 TLS 握手未完成，"
            "通常表示微信内置浏览器的证书信任未生效、没有信任 mitmproxy CA 证书，"
            "或客户端在收到 MITM 证书后主动断开；"
            f"url={latest.get('url_redacted')}"
        )
    if latest.get("reason") == "article_request_seen":
        return (
            f"{base_reason}；MITM 已看到文章主页面请求，但未收到可保存的主 HTML 响应："
            f"url={latest.get('url_redacted')}, "
            f"query_keys={','.join(str(item) for item in latest.get('query_keys') or [])}"
        )
    if latest.get("reason") == "article_main_html_requested":
        return (
            f"{base_reason}；MITM 在 request 阶段已捕获带关键参数的文章主 URL，"
            "但没有收到可保存的 response HTML；"
            "请重点检查该请求是否被客户端取消、命中 304/空响应、本地缓存，或 response 阶段被阻断："
            f"url={latest.get('url_redacted')}, "
            f"query_keys={','.join(str(item) for item in latest.get('query_keys') or [])}"
        )
    if latest.get("reason") == "article_referer_seen":
        return (
            f"{base_reason}；MITM 只从资源请求 Referer 看到文章主 URL，"
            "没有看到微信内置浏览器发出真实文章主请求，因此不能保存文章 HTML；"
            "这通常表示文章正文由本地缓存/XWorker 复用，或主请求没有经过当前代理；"
            f"url={latest.get('url_redacted')}, "
            f"query_keys={','.join(str(item) for item in latest.get('query_keys') or [])}"
        )
    if latest.get("reason") == "article_html_without_key_ignored":
        match_note = ""
        if latest.get("title_matches_target"):
            match_note = f"；response title matches clicked title: {latest.get('title')}"
        return (
            f"{base_reason}；MITM 已在一个微信 HTML response 中看到文章页面特征"
            f"{'，标题=' + str(latest.get('title')) if latest.get('title') else ''}，"
            "但该请求不是带 __biz/mid/idx/sn/key 的文章主请求；"
            "当前规则不会把它当作 original_main.html 保存。"
            f"{match_note}"
            f"url={latest.get('url_redacted')}, "
            f"content_type={latest.get('content_type')}, body_chars={latest.get('body_chars')}"
        )
    if latest.get("reason") == "wechat_response_title_candidate":
        match_note = ""
        if latest.get("title_matches_target"):
            match_note = "；response title candidate matches clicked title"
        candidates = "、".join(str(item) for item in latest.get("title_candidates") or [] if str(item).strip())
        return (
            f"{base_reason}；MITM 已在一个微信 response 中发现文章标题候选"
            f"{'：' + candidates if candidates else ''}"
            f"{match_note}。"
            "这说明文章相关内容可能已经通过其它接口返回，但当前规则只把带 __biz/mid/idx/sn/key 的主 HTML 作为 original_main.html。"
            f"url={latest.get('url_redacted')}, "
            f"content_type={latest.get('content_type')}, body_chars={latest.get('body_chars')}"
        )
    if latest.get("reason") == "wechat_response_target_title_seen":
        runtime_note = format_runtime_params_for_failure_reason(latest.get("runtime_params"))
        return (
            f"{base_reason}；MITM 已在一个微信 response 的正文文本中直接发现点击标题：{latest.get('title')}。"
            f"{runtime_note}"
            "这说明文章相关内容已经通过某个响应返回，但当前规则只把带 __biz/mid/idx/sn/key 的主 HTML 作为 original_main.html。"
            f"url={latest.get('url_redacted')}, "
            f"content_type={latest.get('content_type')}, body_chars={latest.get('body_chars')}"
        )
    if latest.get("reason") == "wechat_tunnel_seen":
        return (
            f"{base_reason}；MITM 已看到微信 HTTPS 隧道，但没有解密到文章主页面请求；"
            "请检查微信内置浏览器是否信任 mitmproxy CA 证书，或本次打开是否只命中了本地缓存；"
            f"url={latest.get('url_redacted')}"
        )
    if is_wechat_resource_diagnostic(latest):
        return (
            f"{base_reason}；MITM 仅看到微信资源域名或静态资源隧道，"
            f"未看到 {WECHAT_ARTICLE_HOST} 文章主页面请求；"
            "请检查文章窗口是否真的重新发起主页面请求、微信内置浏览器是否信任 mitmproxy CA 证书，"
            f"或本次打开是否命中了本地缓存；url={latest.get('url_redacted')}"
        )
    return (
        f"{base_reason}；最近候选请求未保存："
        f"reason={latest.get('reason')}, "
        f"status={latest.get('status_code')}, "
        f"body_chars={latest.get('body_chars')}, "
        f"url={latest.get('url_redacted')}"
    )

def select_mitm_timeout_diagnostic(diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    """从多条 MITM 候选事件中挑最能解释失败的一条，避免静态资源覆盖文章主域名线索。"""
    safe_diagnostics = [item for item in diagnostics if isinstance(item, dict)]
    if not safe_diagnostics:
        return {}

    priority_rules = (
        lambda item: item.get("reason") in {"tls_client_failed", "tls_server_failed"} and is_wechat_article_host_diagnostic(item),
        lambda item: item.get("reason") == "wechat_response_target_title_seen",
        lambda item: item.get("reason") == "wechat_response_title_candidate" and item.get("title_matches_target"),
        lambda item: item.get("reason") == "article_html_without_key_ignored",
        lambda item: item.get("reason") == "wechat_response_title_candidate",
        lambda item: item.get("reason") == "article_main_html_requested",
        lambda item: item.get("reason") == "article_request_seen",
        lambda item: item.get("reason") == "article_referer_seen",
        lambda item: item.get("reason") in {"wechat_tunnel_error", "mitm_flow_error"} and is_wechat_article_host_diagnostic(item),
        lambda item: is_wechat_article_path_diagnostic(item),
        lambda item: is_wechat_article_host_diagnostic(item),
        lambda item: item.get("reason") in {"tls_client_failed", "tls_server_failed"},
        lambda item: item.get("reason") in {"wechat_tunnel_error", "mitm_flow_error"},
    )
    for rule in priority_rules:
        for item in reversed(safe_diagnostics):
            if rule(item):
                return item
    return safe_diagnostics[-1]

def format_runtime_params_for_failure_reason(runtime_params: Any) -> str:
    if not isinstance(runtime_params, dict) or not runtime_params:
        return "该 response 未提取到 key/pass_ticket/appmsg_token 等临时参数；"
    keys = []
    for key in ("__biz", "biz", "mid", "appmsgid", "idx", "sn", "key", "pass_ticket", "appmsg_token", "wxtoken"):
        item = runtime_params.get(key)
        if not isinstance(item, dict):
            continue
        value = item.get("value") or item.get("value_redacted") or ""
        source = item.get("source") or "unknown"
        keys.append(f"{key}={value}({source})")
    if not keys:
        return "该 response 未提取到 key/pass_ticket/appmsg_token 等临时参数；"
    return f"该 response 提取到临时参数摘要：{', '.join(keys)}；"

def has_matching_tls_client_established(diagnostics: list[dict[str, Any]], target: dict[str, Any]) -> bool:
    """判断同一 host 是否已经完成客户端侧 TLS；没有完成时无法进入 HTTP 解密层。"""
    target_host = diagnostic_host(target)
    if not target_host:
        return False
    return any(
        isinstance(item, dict)
        and item.get("reason") == "tls_client_established"
        and diagnostic_host(item) == target_host
        for item in diagnostics
    )

def is_wechat_article_host_diagnostic(diagnostic: dict[str, Any]) -> bool:
    return diagnostic_host(diagnostic) == WECHAT_ARTICLE_HOST

def is_wechat_article_path_diagnostic(diagnostic: dict[str, Any]) -> bool:
    if not is_wechat_article_host_diagnostic(diagnostic):
        return False
    path = str(diagnostic.get("path") or urlparse(str(diagnostic.get("url_redacted") or "")).path or "")
    return path.rstrip("/") == "/s" or path.startswith("/s/")

def is_wechat_resource_diagnostic(diagnostic: dict[str, Any]) -> bool:
    host = diagnostic_host(diagnostic)
    if not host or host == WECHAT_ARTICLE_HOST:
        return False
    return host.endswith(".wx.qq.com") or host.endswith(".weixin.qq.com") or host.endswith(".qq.com")

def diagnostic_host(diagnostic: dict[str, Any]) -> str:
    raw_host = str(diagnostic.get("host") or "").strip().lower()
    if raw_host:
        return raw_host.split("@")[-1].split(":")[0]
    parsed = urlparse(str(diagnostic.get("url_redacted") or ""))
    return str(parsed.hostname or "").strip().lower()

def article_capture_report_from_mitm_event(
    event: dict[str, Any],
    config: dict | None,
    *,
    article_index: int,
) -> dict[str, Any]:
    """把 MITM 主文章事件落到临时文件，并组装成 build_local_article_archive 可消费的 report。"""
    config = config or {}
    output_dir = Path(config.get("output_root") or (LOG_DIR / "article_capture"))
    capture_dir = output_dir / f"mitm_article_{max(1, int(article_index))}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    capture_dir.mkdir(parents=True, exist_ok=True)

    html_text = str(event.get("html_text") or "")
    html_path = capture_dir / "original_main_from_mitm.html"
    html_path.write_text(html_text, encoding="utf-8", errors="ignore")

    request_context = {
        "method": str(event.get("method") or "GET"),
        "request_url": str(event.get("url") or ""),
        "request_headers": dict(event.get("request_headers") or {}),
        "query": event.get("query") or parse_qs(urlparse(str(event.get("url") or "")).query, keep_blank_values=True),
    }
    request_context_path = capture_dir / "original_request_from_mitm.json"
    request_context_path.write_text(
        json.dumps(request_context, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    title = str(event.get("title") or _extract_article_title_from_html(html_text) or f"第 {article_index} 篇文章")
    account_name = first_valid_account_name(config.get("account_name"), extract_account_name_from_html_text(html_text))
    article_url = str(event.get("url") or "")
    article_short_link = first_valid_wechat_article_short_link(event.get("article_short_link"), event.get("short_link"))
    published_time = normalize_published_article_time(event.get("published_article_time"))
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return {
        "created_at": created_at,
        "output_dir": str(capture_dir),
        "target_article": {"title": title},
        "main_html_capture": {
            "url": article_url,
            "url_redacted": str(event.get("url_redacted") or _redact_url(article_url)),
            "private_html_path": str(html_path),
            "request_context_file": str(request_context_path),
            "request_headers": dict(event.get("request_headers") or {}),
            "status_code": event.get("status_code"),
            "response_headers": dict(event.get("response_headers") or {}),
            "captured_time": created_at,
            "source": "mitm",
        },
        "storage": {
            "account_name": account_name,
            "title": title,
            "article_url": article_short_link,
            "article_url_redacted": str(event.get("url_redacted") or _redact_url(article_url)),
        },
        "article_detail": {
            "account_name": account_name,
            "article_title": title,
            "published_article_time": published_time,
            "article_link": article_short_link,
            "article_short_link": article_short_link,
            "short_link": article_short_link,
            "html_text": html_text,
        },
        "comment_fetch": {},
    }

def build_mitm_wait_failed_report(
    config: dict[str, Any],
    article_index: int,
    reason: str,
    mitm_diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "created_at": now,
        "target_article": {"title": f"第 {article_index} 篇文章"},
        "main_html_capture": {},
        "storage": {
            "account_name": first_valid_account_name(config.get("account_name")),
            "title": f"第 {article_index} 篇文章",
        },
        "article_detail": {},
        "comment_fetch": {},
        "mitm_diagnostics": list(mitm_diagnostics or []),
        "automation_error": reason,
        "conclusion": reason,
    }
