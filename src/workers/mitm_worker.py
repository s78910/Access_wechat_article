from __future__ import annotations

import asyncio
import html
import json
import re
import time
from datetime import datetime
from multiprocessing.queues import Queue
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from src.core.config import DEFAULT_DB_PATH, MITMPROXY_CONF_DIR, TMP_DIR
from src.modules.storage.sqlite_store import SQLiteStore


WECHAT_HOST = "mp.weixin.qq.com"
WECHAT_TRAFFIC_HOST_SUFFIXES = ("weixin.qq.com", "wx.qq.com", "qq.com")
SENSITIVE_QUERY_KEYS = {
    "key",
    "pass_ticket",
    "appmsg_token",
    "uin",
    "poc_token",
    "exportkey",
    "sessionid",
    "devicetype",
    "version",
}
ARTICLE_MAIN_HTML_REQUIRED_KEYS = {"__biz", "mid", "idx", "sn"}
ARTICLE_MAIN_HTML_DEDUPE_SECONDS = 60.0
MAX_RESPONSE_TITLE_SCAN_CHARS = 1_000_000
RUNTIME_PARAM_KEYS = (
    "__biz",
    "biz",
    "mid",
    "appmsgid",
    "idx",
    "sn",
    "key",
    "pass_ticket",
    "appmsg_token",
    "wxtoken",
    "uin",
)
SENSITIVE_RUNTIME_PARAM_KEYS = {"key", "pass_ticket", "appmsg_token", "uin", "wxtoken"}
TITLE_CANDIDATE_KEYS = {
    "title",
    "msg_title",
    "appmsg_title",
    "article_title",
    "activity_name",
}


def run_mitm_worker(event_queue: Queue, config: dict | None = None, capture_event_queue: Queue | None = None) -> None:
    """启动 mitmproxy worker，监听用户本机授权打开的微信公众平台请求。"""
    config = config or {}
    host = str(config.get("host", "127.0.0.1"))
    port = int(config.get("port", 18000))
    db_path = Path(config.get("db_path") or DEFAULT_DB_PATH)
    auto_save_content = bool(config.get("auto_save_content", True))
    confdir = Path(config.get("confdir") or MITMPROXY_CONF_DIR)
    ssl_insecure = bool(config.get("ssl_insecure", True))
    run_options = config.get("run_options") if isinstance(config.get("run_options"), dict) else {}
    target_probe_path = Path(config.get("target_probe_path") or (TMP_DIR / "article_capture" / "current_target.json"))

    try:
        from mitmproxy import options
        from mitmproxy.tools.dump import DumpMaster
    except Exception as exc:
        put_event(event_queue, "ERROR", f"mitmproxy 未安装或无法导入：{exc}", source="mitm")
        return

    async def _run() -> None:
        confdir.mkdir(parents=True, exist_ok=True)
        opts = options.Options(
            listen_host=host,
            listen_port=port,
            confdir=str(confdir),
            ssl_insecure=ssl_insecure,
        )
        master = DumpMaster(opts, with_termlog=False, with_dumper=False)
        master.addons.add(
            WeChatCaptureAddon(
                event_queue=event_queue,
                capture_event_queue=capture_event_queue,
                store=SQLiteStore(db_path),
                auto_save_content=auto_save_content,
                target_probe_path=target_probe_path,
            )
        )
        put_event(
            event_queue,
            "INFO",
            f"MITM 代理监听已启动：{host}:{port}；confdir={confdir}；ssl_insecure={ssl_insecure}",
            source="mitm",
        )
        await master.run()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        put_event(event_queue, "INFO", "MITM 代理进程收到退出信号", source="mitm")
    except Exception as exc:
        put_event(event_queue, "ERROR", f"MITM 代理进程异常退出：{exc}", source="mitm")


class WeChatCaptureAddon:
    """mitmproxy 插件：识别微信文章相关接口，并按配置写入 SQLite。"""

    def __init__(
        self,
        event_queue: Queue,
        store: SQLiteStore,
        auto_save_content: bool = True,
        capture_event_queue: Queue | None = None,
        target_probe_path: Path | str | None = None,
    ) -> None:
        self.event_queue = event_queue
        self.capture_event_queue = capture_event_queue or event_queue
        self.store = store
        self.auto_save_content = auto_save_content
        self.target_probe_path = Path(target_probe_path) if target_probe_path else None
        self.article_main_html_seen: dict[str, float] = {}
        self.article_main_html_candidate_seen: dict[str, float] = {}

    def http_connect(self, flow: Any) -> None:
        host, port = extract_connect_address(flow)
        if not is_wechat_host(host):
            return

        url = f"https://{host}/"
        self._emit_article_main_html_candidate_event(
            flow,
            url,
            reason="wechat_tunnel_seen",
            body_chars=0,
            level="INFO",
        )
        put_event(
            self.event_queue,
            "INFO",
            f"MITM 已看到微信 HTTPS 隧道：{host}:{port or 443}",
            source="mitm",
        )

    def http_connect_error(self, flow: Any) -> None:
        host, port = extract_connect_address(flow)
        if not is_wechat_host(host):
            return
        error = stringify_flow_error(flow)
        self._emit_article_main_html_candidate_event(
            flow,
            f"https://{host}/",
            reason="wechat_tunnel_error",
            body_chars=0,
            level="ERROR",
            error=error,
        )

    def tls_clienthello(self, data: Any) -> None:
        client_hello = getattr(data, "client_hello", None)
        host = str(getattr(client_hello, "sni", "") or "")
        if not is_wechat_host(host):
            return
        alpn_protocols = [
            decode_bytes_to_text(item)
            for item in list(getattr(client_hello, "alpn_protocols", []) or [])
        ]
        self._emit_tls_diagnostic(
            data,
            reason="tls_clienthello",
            host=host,
            level="INFO",
            error=f"alpn={','.join(item for item in alpn_protocols if item)}",
        )

    def tls_established_client(self, data: Any) -> None:
        self._emit_tls_diagnostic(data, reason="tls_client_established", level="INFO")

    def tls_established_server(self, data: Any) -> None:
        self._emit_tls_diagnostic(data, reason="tls_server_established", level="INFO")

    def tls_failed_client(self, data: Any) -> None:
        self._emit_tls_diagnostic(data, reason="tls_client_failed")

    def tls_failed_server(self, data: Any) -> None:
        self._emit_tls_diagnostic(data, reason="tls_server_failed")

    def error(self, flow: Any) -> None:
        url = getattr(getattr(flow, "request", None), "pretty_url", "")
        host = urlparse(url).hostname if url else extract_connect_address(flow)[0]
        if not is_wechat_host(host):
            return
        self._emit_article_main_html_candidate_event(
            flow,
            url or f"https://{host}/",
            reason="mitm_flow_error",
            body_chars=0,
            level="ERROR",
            error=stringify_flow_error(flow),
        )

    def request(self, flow: Any) -> None:
        url = getattr(flow.request, "pretty_url", "")
        if is_article_main_html_url(url):
            disable_article_request_cache(flow.request)
            self._emit_article_main_html_request_event(flow, url, url_source="request")
            self._emit_article_main_html_candidate_event(
                flow,
                url,
                reason="article_request_seen",
                body_chars=0,
                level="INFO",
            )
            put_event(
                self.event_queue,
                "INFO",
                f"MITM 已看到文章主页面请求：{redact_article_runtime_url(url)}",
                source="mitm",
            )
        else:
            referer_url = compact_header_value(compact_headers(getattr(flow.request, "headers", {})), "referer")
            if is_article_main_html_url(referer_url):
                self._emit_article_main_html_request_event(
                    flow,
                    referer_url,
                    url_source="referer",
                    carrier_url=url,
                )
                self._emit_article_main_html_candidate_event(
                    flow,
                    referer_url,
                    reason="article_referer_seen",
                    body_chars=0,
                    level="INFO",
                )
                put_event(
                    self.event_queue,
                    "INFO",
                    f"MITM 已从资源请求 Referer 看到文章主 URL，但这不是文章主请求本身：{redact_article_runtime_url(referer_url)}",
                    source="mitm",
                )
            elif is_article_identity_url(url) or is_article_identity_url(referer_url):
                diagnostic_url = url if is_article_identity_url(url) else referer_url
                self._emit_article_main_html_candidate_event(
                    flow,
                    diagnostic_url,
                    reason="article_identity_without_key",
                    body_chars=0,
                    level="WARN",
                )
                put_event(
                    self.event_queue,
                    "WARN",
                    f"MITM 看到文章身份参数但缺少 key：{redact_article_runtime_url(diagnostic_url)}",
                    source="mitm",
                )

        if is_wechat_traffic_url(url):
            put_traffic_event(
                self.event_queue,
                upload_bytes=measure_request_upload_bytes(flow.request),
                download_bytes=0,
                url=url,
            )

        kind = classify_wechat_url(url)
        if not kind:
            return

        put_event(
            self.event_queue,
            "INFO",
            f"捕获微信请求：{kind} {sanitize_url(url)}",
            source="mitm",
        )

    def response(self, flow: Any) -> None:
        url = getattr(flow.request, "pretty_url", "")
        if is_wechat_traffic_url(url):
            put_traffic_event(
                self.event_queue,
                upload_bytes=0,
                download_bytes=measure_response_download_bytes(flow.response),
                url=url,
            )

        if is_article_main_html_url(url):
            disable_article_response_cache(flow.response)
            self._emit_article_main_html_event(flow, url)
        else:
            self._inspect_wechat_response(flow, url)

        if classify_wechat_url(url) != "profile_ext":
            return

        try:
            response_text = flow.response.get_text(strict=False)
            records = extract_article_records_from_profile_response(response_text, url)
            if not records:
                return

            if not self.auto_save_content:
                put_event(
                    self.event_queue,
                    "INFO",
                    f"已解析文章记录 {len(records)} 条，因内容自动保存关闭未写入数据库",
                    source="mitm",
                )
                return

            saved_count = 0
            for record in records:
                self.store.save_public_article(record)
                saved_count += 1
            put_event(
                self.event_queue,
                "SUCCESS",
                f"已解析并保存文章记录 {saved_count} 条",
                source="mitm",
            )
        except Exception as exc:
            put_event(self.event_queue, "WARN", f"profile_ext 响应解析失败：{exc}", source="mitm")

    def _inspect_wechat_response(self, flow: Any, url: str) -> None:
        if not is_wechat_traffic_url(url):
            return

        response_headers = compact_headers(getattr(flow.response, "headers", {}))
        content_type = compact_header_value(response_headers, "content-type").lower()
        if "html" not in content_type:
            if is_textual_response_content_type(content_type):
                if self._emit_realtime_large_response_probe_if_needed(flow, url):
                    return
                response_text = read_flow_response_text(flow)
                self._emit_realtime_response_probe(flow, url, response_text)
                if self._emit_target_title_seen_if_matched(flow, url, response_text):
                    return
                title_candidates = extract_title_candidates_from_response_text(response_text)
                if title_candidates:
                    self._emit_article_main_html_candidate_event(
                        flow,
                        url,
                        reason="wechat_response_title_candidate",
                        body_chars=len(str(response_text or "")),
                        level="INFO",
                        title=title_candidates[0],
                        title_matched=True,
                        title_candidates=title_candidates,
                    )
                    put_event(
                        self.event_queue,
                        "INFO",
                        f"MITM 已在微信文本 response 中发现标题候选：title={title_candidates[0]} url={redact_article_runtime_url(url)}",
                        source="mitm",
                    )
                    return
            if is_article_related_mp_url(url):
                self._emit_article_main_html_candidate_event(
                    flow,
                    url,
                    reason="non_html_response",
                    body_chars=measure_content_bytes(getattr(flow, "response", None)),
            )
            return

        if self._emit_realtime_large_response_probe_if_needed(flow, url):
            return
        html_text = read_flow_response_text(flow)
        self._emit_realtime_response_probe(flow, url, html_text)
        if self._emit_target_title_seen_if_matched(flow, url, html_text):
            return
        if looks_like_wechat_article_html(html_text):
            article_title = extract_article_title_from_html(html_text)
            self._emit_article_main_html_candidate_event(
                flow,
                url,
                reason="article_html_without_key_ignored",
                body_chars=len(str(html_text or "")),
                level="INFO",
                title=article_title,
                title_matched=bool(article_title),
                title_candidates=extract_title_candidates_from_response_text(html_text),
            )
            put_event(
                self.event_queue,
                "INFO",
                f"MITM 已在非带 key 的微信 HTML response 中看到文章内容特征：title={article_title or '未识别'} url={redact_article_runtime_url(url)}",
                source="mitm",
            )
            return

        title_candidates = extract_title_candidates_from_response_text(html_text)
        if title_candidates:
            self._emit_article_main_html_candidate_event(
                flow,
                url,
                reason="wechat_response_title_candidate",
                body_chars=len(str(html_text or "")),
                level="INFO",
                title=title_candidates[0],
                title_matched=True,
                title_candidates=title_candidates,
            )
            put_event(
                self.event_queue,
                "INFO",
                f"MITM 已在微信 HTML response 中发现标题候选：title={title_candidates[0]} url={redact_article_runtime_url(url)}",
                source="mitm",
            )
            return

        if not is_article_related_mp_url(url):
            return

        self._emit_article_main_html_candidate_event(
            flow,
            url,
            reason="unrecognized_wechat_html",
            body_chars=len(str(html_text or "")),
        )

    def _emit_target_title_seen_if_matched(self, flow: Any, url: str, response_text: str) -> bool:
        target_title = self._read_current_target_title()
        if not target_title:
            return False
        if not response_text_contains_title(response_text, target_title):
            return False
        runtime_params = extract_runtime_params_summary(url, response_text)
        self._emit_article_main_html_candidate_event(
            flow,
            url,
            reason="wechat_response_target_title_seen",
            body_chars=len(str(response_text or "")),
            level="INFO",
            title=target_title,
            title_matched=True,
            title_candidates=[target_title],
            runtime_params=runtime_params,
        )
        put_event(
            self.event_queue,
            "INFO",
            (
                f"MITM 已在微信 response 正文中命中本轮点击标题：title={target_title} "
                f"runtime_params={format_runtime_param_keys_for_log(runtime_params)} "
                f"url={redact_article_runtime_url(url)}"
            ),
            source="mitm",
        )
        return True

    def _emit_realtime_large_response_probe_if_needed(self, flow: Any, url: str) -> bool:
        if not self._read_current_target_title():
            return False
        body_bytes = measure_content_bytes(getattr(flow, "response", None))
        if body_bytes <= MAX_RESPONSE_TITLE_SCAN_CHARS:
            return False
        runtime_params = extract_runtime_params_summary(url, "")
        self._emit_article_main_html_candidate_event(
            flow,
            url,
            reason="realtime_response_body_too_large",
            body_chars=body_bytes,
            level="WARN",
            runtime_params=runtime_params,
        )
        put_event(
            self.event_queue,
            "WARN",
            (
                f"MITM 5秒实时探针跳过大响应正文扫描：body_bytes={body_bytes} "
                f"request={redact_article_runtime_url(url)} "
                f"runtime_params={format_runtime_param_keys_for_log(runtime_params)}"
            ),
            source="mitm",
        )
        return True

    def _emit_realtime_response_probe(self, flow: Any, url: str, response_text: str) -> None:
        probe = self._read_current_target_probe()
        target_title = str(probe.get("target_title") or "").strip()
        if not target_title:
            return
        title_matched = response_text_contains_title(response_text, target_title)
        runtime_params = extract_runtime_params_summary(url, response_text)
        reason = "realtime_response_title_match" if title_matched else "realtime_response_checked"
        self._emit_article_main_html_candidate_event(
            flow,
            url,
            reason=reason,
            body_chars=len(str(response_text or "")),
            level="INFO",
            title=target_title if title_matched else "",
            title_matched=title_matched,
            title_candidates=[target_title] if title_matched else [],
            runtime_params=runtime_params,
            probe_window_seconds=float(probe.get("inspect_duration_seconds") or 0.0),
        )
        if title_matched:
            put_event(
                self.event_queue,
                "INFO",
                (
                    f"MITM 5秒实时探针命中点击标题：title={target_title} "
                    f"request={redact_article_runtime_url(url)} "
                    f"runtime_params={format_runtime_param_keys_for_log(runtime_params)}"
                ),
                source="mitm",
            )

    def _read_current_target_probe(self) -> dict[str, Any]:
        if self.target_probe_path is None:
            return {}
        try:
            payload = json.loads(self.target_probe_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        now = time.time()
        try:
            updated_at = float(payload.get("updated_at") or 0)
        except (TypeError, ValueError):
            updated_at = 0
        try:
            inspect_until = float(payload.get("inspect_until") or 0)
        except (TypeError, ValueError):
            inspect_until = 0
        if inspect_until:
            if now > inspect_until:
                return {}
        elif updated_at and now - updated_at > ARTICLE_MAIN_HTML_DEDUPE_SECONDS:
            return {}
        return payload

    def _read_current_target_title(self) -> str:
        payload = self._read_current_target_probe()
        return str(payload.get("target_title") or "").strip()

    def _has_active_capture_probe(self) -> bool:
        # 真实主流程会传入 current_target.json；没有有效探针时不把 MITM 事件压入采集队列。
        if self.target_probe_path is None:
            return True
        return bool(self._read_current_target_probe())

    def _put_capture_event(self, event: dict[str, Any]) -> bool:
        if not self._has_active_capture_probe():
            return False
        self.capture_event_queue.put(event)
        return True

    def _emit_article_main_html_event(self, flow: Any, url: str, html_text: str | None = None) -> None:
        if html_text is None:
            html_text = read_flow_response_text(flow)
        if not str(html_text).strip():
            self._emit_article_main_html_candidate_event(
                flow,
                url,
                reason="empty_html",
                body_chars=0,
            )
            return

        event = build_article_main_html_capture_event(
            url=url,
            method=str(getattr(flow.request, "method", "GET") or "GET"),
            request_headers=compact_headers(getattr(flow.request, "headers", {})),
            response_headers=compact_headers(getattr(flow.response, "headers", {})),
            html_text=html_text,
            status_code=int(getattr(flow.response, "status_code", 0) or 0),
        )
        if not self._put_capture_event(event):
            return
        put_event(
            self.event_queue,
            "SUCCESS",
            f"已捕获文章主 HTML：{event.get('title') or sanitize_url(url)}",
            source="mitm",
        )

    def _emit_article_main_html_request_event(
        self,
        flow: Any,
        url: str,
        *,
        url_source: str = "request",
        carrier_url: str = "",
    ) -> None:
        event = build_article_main_html_request_event(
            url=url,
            method=str(getattr(flow.request, "method", "GET") or "GET"),
            request_headers=compact_headers(getattr(flow.request, "headers", {})),
            url_source=url_source,
            carrier_url=carrier_url,
        )
        if not self._put_capture_event(event):
            return
        self._emit_auth_status_event(event)
        put_event(
            self.event_queue,
            "SUCCESS",
            f"已捕获文章主请求 URL：{event.get('url_redacted')}",
            source="mitm",
        )

    def _emit_auth_status_event(self, request_event: dict[str, Any]) -> None:
        """把“已看到带 key URL”的事实同步给状态页，不暴露原始 key。"""
        put_event(
            self.event_queue,
            "SUCCESS",
            "MITM 已获取文章鉴权参数",
            source="mitm",
            type="auth_status",
            status="captured",
            statusLabel="已获取鉴权",
            hasKeyUrl=True,
            urlRedacted=str(request_event.get("url_redacted") or ""),
            urlSource=str(request_event.get("url_source") or ""),
        )

    def _emit_article_main_html_candidate_event(
        self,
        flow: Any,
        url: str,
        *,
        reason: str,
        body_chars: int,
        level: str = "WARN",
        error: str = "",
        title: str = "",
        title_matched: bool = False,
        title_candidates: list[str] | None = None,
        runtime_params: dict[str, Any] | None = None,
        probe_window_seconds: float | None = None,
    ) -> None:
        now = time.time()
        prune_expired_article_cache(self.article_main_html_candidate_seen, now)
        response = getattr(flow, "response", None)
        identity = f"{article_main_html_identity(url)}|{reason}|{getattr(response, 'status_code', '')}"
        if identity in self.article_main_html_candidate_seen:
            return
        self.article_main_html_candidate_seen[identity] = now

        event = build_article_main_html_candidate_event(
            url=url,
            reason=reason,
            status_code=int(getattr(response, "status_code", 0) or 0),
            response_headers=compact_headers(getattr(response, "headers", {})),
            body_chars=body_chars,
            level=level,
            method=str(getattr(getattr(flow, "request", None), "method", "") or ""),
            error=error,
            title=title,
            title_matched=title_matched,
            title_candidates=title_candidates,
            runtime_params=runtime_params,
            probe_window_seconds=probe_window_seconds,
        )
        if not self._put_capture_event(event):
            return
        put_event(
            self.event_queue,
            level,
            f"MITM 已看到文章页候选请求但未保存主 HTML：{reason} {event.get('url_redacted')}",
            source="mitm",
        )

    def _emit_tls_diagnostic(
        self,
        data: Any,
        *,
        reason: str,
        host: str | None = None,
        level: str | None = None,
        error: str = "",
    ) -> None:
        conn = getattr(data, "conn", None)
        conn_host, port = extract_connection_endpoint(conn)
        host = host or conn_host
        if not is_wechat_host(host):
            return
        diagnostic_level = level or ("ERROR" if "failed" in reason else "INFO")
        error = str(error or getattr(conn, "error", "") or "")
        event = build_article_main_html_candidate_event(
            url=f"https://{host}/",
            reason=reason,
            status_code=0,
            response_headers={},
            body_chars=0,
            level=diagnostic_level,
            method="CONNECT",
            error=error,
        )
        if not self._put_capture_event(event):
            return
        put_event(
            self.event_queue,
            diagnostic_level,
            f"MITM TLS 诊断：{reason} {host}:{port or 443} {error}",
            source="mitm",
        )


def prune_expired_article_cache(
    cache: dict[str, float],
    now: float | None = None,
    ttl_seconds: float = ARTICLE_MAIN_HTML_DEDUPE_SECONDS,
) -> None:
    """清理超过去重窗口的文章捕获记录，避免常驻 MITM 缓存无限增长。"""
    current_time = time.time() if now is None else float(now)
    ttl = max(0.0, float(ttl_seconds))
    expired_keys = [
        key
        for key, seen_at in cache.items()
        if current_time - float(seen_at or 0.0) > ttl
    ]
    for key in expired_keys:
        cache.pop(key, None)


def disable_article_request_cache(request: Any) -> None:
    """禁止微信文章页使用条件缓存，尽量让重复打开也返回完整 HTML。"""
    headers = getattr(request, "headers", None)
    if headers is None:
        return
    remove_headers_case_insensitive(headers, ("If-None-Match", "If-Modified-Since"))
    set_header(headers, "Cache-Control", "no-cache, no-store, max-age=0")
    set_header(headers, "Pragma", "no-cache")


def disable_article_response_cache(response: Any) -> None:
    """清掉响应缓存标记，避免微信内置浏览器后续复用 304/本地缓存。"""
    headers = getattr(response, "headers", None)
    if headers is None:
        return
    remove_headers_case_insensitive(headers, ("ETag", "Last-Modified"))
    set_header(headers, "Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    set_header(headers, "Pragma", "no-cache")
    set_header(headers, "Expires", "0")
    set_header(headers, "Clear-Site-Data", '"cache"')


def remove_headers_case_insensitive(headers: Any, names: tuple[str, ...]) -> None:
    targets = {name.lower() for name in names}
    try:
        keys = list(headers.keys())
    except AttributeError:
        return
    for key in keys:
        if str(key).lower() in targets:
            try:
                del headers[key]
            except Exception:
                try:
                    headers.pop(key, None)
                except Exception:
                    pass


def set_header(headers: Any, name: str, value: str) -> None:
    try:
        headers[name] = value
    except Exception:
        try:
            headers.set(name, value)
        except Exception:
            pass


def classify_wechat_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc != WECHAT_HOST:
        return ""

    if parsed.path.endswith("/mp/profile_ext"):
        return "profile_ext"
    if parsed.path.endswith("/mp/getappmsgext"):
        return "getappmsgext"
    if parsed.path.endswith("/mp/appmsg_comment"):
        return "appmsg_comment"
    return ""


def is_article_main_html_url(url: str) -> bool:
    parsed = urlparse(url)
    # 文章主请求的域名可能随微信调度变化，不能写死为 mp.weixin.qq.com。
    if not parsed.scheme or not parsed.netloc:
        return False
    query = parse_qs(parsed.query, keep_blank_values=True)
    if not (query.get("key") or [""])[0]:
        return False
    query_keys = set(query.keys())
    has_biz = "__biz" in query_keys or "biz" in query_keys
    return has_biz and {"mid", "idx", "sn"}.issubset(query_keys)


def is_article_identity_url(url: str) -> bool:
    """识别携带文章身份参数的 URL；不要求 key，用于诊断被过滤的候选请求。"""
    parsed = urlparse(str(url or ""))
    if not parsed.scheme or not parsed.netloc:
        return False
    query_keys = set(parse_qs(parsed.query, keep_blank_values=True).keys())
    has_biz = "__biz" in query_keys or "biz" in query_keys
    return has_biz and {"mid", "idx", "sn"}.issubset(query_keys)


def is_wechat_mp_url(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() == WECHAT_HOST


def is_article_related_mp_url(url: str) -> bool:
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() != WECHAT_HOST:
        return False
    path = parsed.path.rstrip("/")
    query_keys = set(parse_qs(parsed.query, keep_blank_values=True).keys())
    if ARTICLE_MAIN_HTML_REQUIRED_KEYS.issubset(query_keys):
        return True
    return path.startswith("/s") or "appmsg" in path


def is_textual_response_content_type(content_type: str) -> bool:
    """只扫描可解码文本响应，避免误读图片、视频、字体等二进制资源。"""
    value = str(content_type or "").lower()
    if not value:
        return False
    textual_markers = (
        "json",
        "javascript",
        "text/",
        "xml",
        "x-www-form-urlencoded",
    )
    return any(marker in value for marker in textual_markers)


def read_flow_response_text(flow: Any) -> str:
    response = getattr(flow, "response", None)
    if measure_content_bytes(response) > MAX_RESPONSE_TITLE_SCAN_CHARS:
        return ""
    try:
        return str(response.get_text(strict=False) or "")
    except Exception:
        raw_content = getattr(response, "raw_content", b"") or b""
        return raw_content.decode("utf-8", errors="ignore")


def looks_like_wechat_article_html(html_text: str) -> bool:
    """按正文 HTML 特征兜底识别文章页，避免微信换路径后漏捕获。"""
    text = str(html_text or "")
    if not text.strip():
        return False

    lowered = text.lower()
    if "var msg_title" in lowered:
        return True
    has_article_root = 'id="js_article"' in lowered or "id='js_article'" in lowered
    has_article_data = any(marker in lowered for marker in ("js_content", "var publish_time", "var ct", "msg_link"))
    return has_article_root and has_article_data


def extract_title_candidates_from_response_text(response_text: str) -> list[str]:
    """从微信响应文本中轻量提取标题候选，只用于诊断，不保存完整响应体。"""
    text = str(response_text or "")
    if not text.strip():
        return []

    candidates: list[str] = []
    html_title = extract_article_title_from_html(text)
    if html_title:
        candidates.append(html_title)

    patterns = [
        r"\b(?:var\s+)?(?P<key>msg_title|appmsg_title|article_title|activity_name)\b\s*=\s*['\"](?P<value>[^'\"]{1,160})['\"]",
        r"['\"](?P<key>title|msg_title|appmsg_title|article_title|activity_name)['\"]\s*:\s*['\"](?P<value>[^'\"]{1,160})['\"]",
        r"(?is)<h1[^>]+id=['\"]activity-name['\"][^>]*>(?P<value>.*?)</h1>",
        r"(?is)<h1[^>]*>(?P<value>.*?)</h1>",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            key = str(match.groupdict().get("key") or "").lower()
            if key and key not in TITLE_CANDIDATE_KEYS:
                continue
            value = normalize_title_candidate(match.group("value"))
            if is_useful_title_candidate(value):
                candidates.append(value)

    return dedupe_preserve_order(candidates)[:5]


def normalize_title_candidate(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = text.replace("\\/", "/").replace("\\u0026", "&").replace("\\x26", "&")
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_useful_title_candidate(value: str) -> bool:
    text = str(value or "").strip()
    if len(text) < 2 or len(text) > 120:
        return False
    if text.lower() in {"true", "false", "null", "undefined"}:
        return False
    if re.fullmatch(r"[\d._:-]+", text):
        return False
    return True


def response_text_contains_title(response_text: Any, target_title: Any) -> bool:
    """用标准化后的文本做包含判断，验证文章内容是否已经通过其它响应返回。"""
    normalized_body = normalize_compare_text(response_text)
    normalized_title = normalize_compare_text(target_title)
    return bool(normalized_body and normalized_title and normalized_title in normalized_body)


def extract_runtime_params_summary(url: str, response_text: Any) -> dict[str, dict[str, Any]]:
    """提取命中标题 response 中出现的临时参数摘要；不保存完整响应体。"""
    result: dict[str, dict[str, Any]] = {}
    for key, values in parse_qs(urlparse(str(url or "")).query, keep_blank_values=True).items():
        normalized_key = normalize_runtime_param_key(key)
        if normalized_key not in RUNTIME_PARAM_KEYS or not values:
            continue
        result[normalized_key] = build_runtime_param_summary(normalized_key, values[0], "url_query")

    body_text = str(response_text or "")
    for key, value in extract_runtime_param_pairs_from_text(body_text):
        normalized_key = normalize_runtime_param_key(key)
        if normalized_key not in RUNTIME_PARAM_KEYS:
            continue
        # response body 优先，便于验证“参数是否确实在响应里”。
        result[normalized_key] = build_runtime_param_summary(normalized_key, value, "response_body")
    return result


def extract_runtime_param_pairs_from_text(text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    key_pattern = "|".join(re.escape(key) for key in RUNTIME_PARAM_KEYS)
    patterns = (
        rf"['\"](?P<key>{key_pattern})['\"]\s*:\s*['\"](?P<value>[^'\"\s]{{1,600}})['\"]",
        rf"\b(?P<key>{key_pattern})\b\s*=\s*['\"](?P<value>[^'\"\s]{{1,600}})['\"]",
        rf"(?:[?&]|\\u0026|&amp;)(?P<key>{key_pattern})=(?P<value>[^&\\\"'\s<>]{{1,600}})",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, str(text or "")):
            pairs.append((match.group("key"), normalize_runtime_param_value(match.group("value"))))
    return pairs


def normalize_runtime_param_key(key: Any) -> str:
    text = str(key or "").strip()
    return "__biz" if text == "__biz" else text.lower()


def normalize_runtime_param_value(value: Any) -> str:
    text = html.unescape(str(value or "")).strip()
    return text.replace("\\/", "/").replace("\\u0026", "&").replace("\\x26", "&")


def build_runtime_param_summary(key: str, value: Any, source: str) -> dict[str, Any]:
    text = normalize_runtime_param_value(value)
    summary = {
        "source": source,
        "length": len(text),
        "value_redacted": redact_runtime_param_value(key, text),
    }
    if key not in SENSITIVE_RUNTIME_PARAM_KEYS:
        summary["value"] = text
    return summary


def redact_runtime_param_value(key: str, value: Any) -> str:
    text = str(value or "")
    if key not in SENSITIVE_RUNTIME_PARAM_KEYS:
        return text
    if len(text) <= 6:
        return "***"
    return f"{text[:3]}...{text[-4:]}"


def format_runtime_param_keys_for_log(runtime_params: dict[str, Any]) -> str:
    if not runtime_params:
        return "none"
    parts = []
    for key in RUNTIME_PARAM_KEYS:
        item = runtime_params.get(key)
        if not isinstance(item, dict):
            continue
        source = item.get("source") or "unknown"
        value = item.get("value") or item.get("value_redacted") or ""
        parts.append(f"{key}({source})={value}")
    return ", ".join(parts) if parts else "none"


def normalize_compare_text(value: Any) -> str:
    text = html.unescape(str(value or "")).replace("\u200b", "").lower()
    return re.sub(r"\s+", "", text)


def dedupe_preserve_order(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def article_main_html_identity(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    parts = [
        (query.get("__biz") or [""])[0],
        (query.get("mid") or [""])[0],
        (query.get("idx") or [""])[0],
        (query.get("sn") or [""])[0],
    ]
    identity = "|".join(parts).strip("|")
    return identity or url


def build_article_main_html_capture_event(
    *,
    url: str,
    method: str,
    request_headers: dict[str, Any],
    response_headers: dict[str, Any],
    html_text: str,
    status_code: int,
) -> dict[str, Any]:
    """构造文章主 HTML 捕获事件，只保留后续归档必需的请求和响应信息。"""
    return {
        "type": "article_main_html_captured",
        "source": "mitm",
        "level": "SUCCESS",
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "timestamp": time.time(),
        "method": method or "GET",
        "url": url,
        "url_redacted": redact_article_runtime_url(url),
        "query": parse_qs(urlparse(url).query, keep_blank_values=True),
        "request_headers": dict(request_headers or {}),
        "response_headers": dict(response_headers or {}),
        "status_code": int(status_code or 0),
        "title": extract_article_title_from_html(html_text),
        "published_article_time": extract_publish_time_from_html(html_text),
        "article_short_link": extract_article_short_link_from_html(html_text),
        "html_text": html_text,
    }


def build_article_main_html_request_event(
    *,
    url: str,
    method: str,
    request_headers: dict[str, Any],
    url_source: str = "request",
    carrier_url: str = "",
) -> dict[str, Any]:
    """请求阶段立即记录带 key 的文章主 URL，避免 response 未返回时丢失关键参数。"""
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    carrier_url_text = str(carrier_url or "")
    return {
        "type": "article_main_html_requested",
        "source": "mitm",
        "level": "SUCCESS",
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "timestamp": time.time(),
        "method": method or "GET",
        "url": url,
        "url_redacted": redact_article_runtime_url(url),
        "host": parsed.netloc,
        "path": parsed.path,
        "query": query,
        "query_keys": sorted(query.keys()),
        "request_headers": dict(request_headers or {}),
        "url_source": str(url_source or "request"),
        "carrier_url_redacted": redact_article_runtime_url(carrier_url_text) if carrier_url_text else "",
    }


def build_article_main_html_candidate_event(
    *,
    url: str,
    reason: str,
    status_code: int,
    response_headers: dict[str, Any],
    body_chars: int,
    level: str = "WARN",
    method: str = "",
    error: str = "",
    title: str = "",
    title_matched: bool = False,
    title_candidates: list[str] | None = None,
    runtime_params: dict[str, Any] | None = None,
    probe_window_seconds: float | None = None,
) -> dict[str, Any]:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    safe_title_candidates = [
        item
        for item in dedupe_preserve_order(str(value or "").strip() for value in (title_candidates or []))
        if item
    ][:5]
    return {
        "type": "article_main_html_candidate",
        "source": "mitm",
        "level": level,
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "timestamp": time.time(),
        "reason": reason,
        "url_redacted": redact_article_runtime_url(url),
        "request_url_redacted": redact_article_runtime_url(url),
        "host": parsed.netloc,
        "path": parsed.path,
        "method": method,
        "query_keys": sorted(query.keys()),
        "status_code": int(status_code or 0),
        "content_type": compact_header_value(response_headers, "content-type"),
        "body_chars": max(0, int(body_chars or 0)),
        "error": str(error or ""),
        "title": str(title or ""),
        "title_matched": bool(title_matched),
        "title_candidates": safe_title_candidates,
        "runtime_params": dict(runtime_params or {}),
        "probe_window_seconds": probe_window_seconds,
    }


def compact_headers(headers: Any) -> dict[str, str]:
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
    try:
        items = headers.items(multi=True)
    except TypeError:
        items = headers.items()
    except AttributeError:
        return result

    for key, value in items:
        lowered = str(key).lower()
        if lowered in excluded or value in (None, ""):
            continue
        if "\r" in lowered or "\n" in lowered:
            continue
        text = str(value)
        if "\r" in text or "\n" in text:
            continue
        result[lowered] = text
    return result


def compact_header_value(headers: dict[str, Any], name: str) -> str:
    target = name.lower()
    for key, value in dict(headers or {}).items():
        if str(key).lower() == target:
            return str(value)
    return ""


def redact_article_runtime_url(url: str) -> str:
    parsed = urlparse(url)
    safe_pairs = []
    for key, values in parse_qs(parsed.query, keep_blank_values=True).items():
        if key in SENSITIVE_QUERY_KEYS:
            continue
        for value in values:
            safe_pairs.append((key, value))
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(safe_pairs), parsed.fragment))


def extract_article_title_from_html(html_text: str) -> str:
    patterns = (
        r"var\s+msg_title\s*=\s*['\"](?P<value>.*?)['\"]",
        r"(?i)<meta[^>]+property=['\"]og:title['\"][^>]+content=['\"](?P<value>.*?)['\"]",
        r"(?is)<h1[^>]+id=['\"]activity-name['\"][^>]*>(?P<value>.*?)</h1>",
        r"(?is)<title[^>]*>(?P<value>.*?)</title>",
    )
    for pattern in patterns:
        match = re.search(pattern, html_text or "")
        if not match:
            continue
        value = html.unescape(match.group("value"))
        value = re.sub(r"\s+", " ", value).strip()
        if value:
            return value
    return ""


def extract_publish_time_from_html(html_text: str) -> str:
    timestamp_match = re.search(r"var\s+ct\s*=\s*['\"](?P<value>\d{8,})['\"]", html_text or "")
    if timestamp_match:
        return format_publish_time(timestamp_match.group("value"))

    text_match = re.search(r"var\s+publish_time\s*=\s*['\"](?P<value>[^'\"]+)['\"]", html_text or "")
    if text_match:
        return normalize_publish_time_text(text_match.group("value"))
    return ""


def extract_article_short_link_from_html(html_text: str) -> str:
    patterns = (
        r"(?:window\.)?short_link\s*=\s*['\"](?P<value>.*?)['\"]",
        r"var\s+msg_link\s*=\s*['\"](?P<value>.*?)['\"]",
        r"(?i)<meta[^>]+property=['\"]og:url['\"][^>]+content=['\"](?P<value>.*?)['\"]",
        r"(?i)<link[^>]+rel=['\"]canonical['\"][^>]+href=['\"](?P<value>.*?)['\"]",
        r"https://mp\.weixin\.qq\.com/s/[A-Za-z0-9_\-]+",
    )
    for pattern in patterns:
        match = re.search(pattern, html_text or "")
        if not match:
            continue
        value = normalize_article_link_value(match.group("value") if "value" in match.groupdict() else match.group(0))
        if value:
            short_link = normalize_wechat_article_short_link(value)
            if short_link:
                return short_link
    return ""


def normalize_article_link_value(value: str) -> str:
    text = html.unescape(str(value or "")).strip()
    text = text.replace("\\/", "/").replace("\\x26", "&").replace("\\u0026", "&")
    return text


def normalize_wechat_article_short_link(value: str) -> str:
    """只接受 https://mp.weixin.qq.com/s/xxxx，避免把带 key 的主 URL 当短链。"""
    text = normalize_article_link_value(value).strip("'\"")
    parsed = urlparse(text)
    if (parsed.scheme or "").lower() != "https":
        return ""
    if (parsed.hostname or "").lower() != WECHAT_HOST:
        return ""
    path = parsed.path.rstrip("/")
    if not path.startswith("/s/"):
        return ""
    slug = path.removeprefix("/s/").strip("/")
    if not slug:
        return ""
    return urlunparse(("https", WECHAT_HOST, f"/s/{slug}", "", "", ""))


def normalize_publish_time_text(value: Any) -> str:
    """文章发布时间按页面展示精度保存到分钟，不补不存在的秒。"""
    text = str(value or "").strip().replace("T", " ")
    if not text:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", text):
        return text
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}) (\d{2})-(\d{2})", text)
    if match:
        return f"{match.group(1)} {match.group(2)}:{match.group(3)}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}.*", text):
        return text[:16]
    return text


def is_wechat_traffic_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.split("@")[-1].split(":")[0].lower()
    if not host:
        return False

    return is_wechat_host(host)


def is_wechat_host(host: str) -> bool:
    value = str(host or "").split("@")[-1].split(":")[0].lower()
    if not value:
        return False
    return any(
        value == suffix or value.endswith(f".{suffix}")
        for suffix in WECHAT_TRAFFIC_HOST_SUFFIXES
    )


def extract_connect_address(flow: Any) -> tuple[str, int]:
    server_conn = getattr(flow, "server_conn", None)
    address = getattr(server_conn, "address", None)
    if isinstance(address, (list, tuple)) and address:
        host = str(address[0] or "")
        try:
            port = int(address[1] or 0) if len(address) > 1 else 0
        except (TypeError, ValueError):
            port = 0
        return host, port

    request = getattr(flow, "request", None)
    host = str(getattr(request, "host", "") or "")
    try:
        port = int(getattr(request, "port", 0) or 0)
    except (TypeError, ValueError):
        port = 0
    return host, port


def extract_connection_endpoint(conn: Any) -> tuple[str, int]:
    address = getattr(conn, "address", None)
    if not address:
        address = getattr(conn, "peername", None)
    if isinstance(address, (list, tuple)) and address:
        host = str(address[0] or "")
        try:
            port = int(address[1] or 0) if len(address) > 1 else 0
        except (TypeError, ValueError):
            port = 0
        return host, port
    sni = str(getattr(conn, "sni", "") or "")
    return sni, 443 if sni else 0


def stringify_flow_error(flow: Any) -> str:
    error = getattr(flow, "error", None)
    if error is None:
        return ""
    for attr_name in ("msg", "message", "error"):
        value = getattr(error, attr_name, None)
        if value:
            return str(value)
    return str(error)


def measure_request_upload_bytes(request: Any) -> int:
    method = str(getattr(request, "method", "GET") or "GET")
    url = str(getattr(request, "pretty_url", "") or "")
    version = str(getattr(request, "http_version", "HTTP/1.1") or "HTTP/1.1")
    start_line = f"{method} {url} {version}\r\n"

    return (
        len(start_line.encode("utf-8", errors="ignore"))
        + measure_headers_bytes(getattr(request, "headers", None))
        + measure_content_bytes(request)
        + 2
    )


def measure_response_download_bytes(response: Any) -> int:
    version = str(getattr(response, "http_version", "HTTP/1.1") or "HTTP/1.1")
    status_code = str(getattr(response, "status_code", "") or "")
    reason = str(getattr(response, "reason", "") or "")
    status_line = f"{version} {status_code} {reason}\r\n"

    return (
        len(status_line.encode("utf-8", errors="ignore"))
        + measure_headers_bytes(getattr(response, "headers", None))
        + measure_content_bytes(response)
        + 2
    )


def measure_content_bytes(message: Any) -> int:
    content = getattr(message, "raw_content", None)
    if content is None:
        content = getattr(message, "content", None)
    if content is None:
        return 0
    if isinstance(content, str):
        return len(content.encode("utf-8", errors="ignore"))

    try:
        return len(content)
    except TypeError:
        return 0


def decode_bytes_to_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return str(value or "")


def measure_headers_bytes(headers: Any) -> int:
    if not headers:
        return 0

    try:
        items = headers.items(multi=True)
    except TypeError:
        items = headers.items()
    except AttributeError:
        return 0

    total = 0
    for key, value in items:
        total += len(f"{key}: {value}\r\n".encode("utf-8", errors="ignore"))
    return total


def sanitize_url(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    safe_query = {
        key: value
        for key, value in query.items()
        if key not in SENSITIVE_QUERY_KEYS and key in {"action", "__biz"}
    }
    sanitized_query = urlencode(safe_query, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", sanitized_query, ""))


def extract_article_records_from_profile_response(response_text: str, url: str) -> list[dict]:
    payload = json.loads(response_text)
    raw_general_list = payload.get("general_msg_list")
    if not raw_general_list:
        return []

    general_list = json.loads(raw_general_list)
    account_name = extract_account_name_from_url(url)
    records: list[dict] = []

    for item in general_list.get("list", []):
        collect_time = format_collect_time(item.get("comm_msg_info", {}).get("datetime"))
        app_info = item.get("app_msg_ext_info") or {}
        append_article_record(records, account_name, app_info, collect_time)

        for child in app_info.get("multi_app_msg_item_list") or []:
            append_article_record(records, account_name, child, collect_time)

    return records


def append_article_record(records: list[dict], account_name: str, app_info: dict, collect_time: str) -> None:
    title = str(app_info.get("title") or "").strip()
    article_link = str(app_info.get("content_url") or app_info.get("link") or "").strip()
    if not title or not article_link:
        return

    records.append(
        {
            "account_name": account_name,
            "article_title": title,
            "published_article_time": collect_time,
            "article_link": article_link,
            "record_type": "文章列表",
            "collect_time": collect_time,
            "duration_seconds": 0,
            "collect_status": "saved",
        }
    )


def extract_account_name_from_url(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    return (query.get("__biz") or query.get("biz") or ["未知公众号"])[0]


def format_collect_time(timestamp: Any) -> str:
    try:
        return datetime.fromtimestamp(int(timestamp)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def format_publish_time(timestamp: Any) -> str:
    try:
        return datetime.fromtimestamp(int(timestamp)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return datetime.now().strftime("%Y-%m-%d %H:%M")


def put_event(event_queue: Queue, level: str, message: str, source: str = "worker", **extra) -> None:
    event = {
        "level": level,
        "message": message,
        "source": source,
        "createdAt": datetime.now().isoformat(timespec="seconds"),
    }
    event.update(extra)
    event_queue.put(event)


def put_traffic_event(
    event_queue: Queue,
    upload_bytes: int,
    download_bytes: int,
    url: str,
    source: str = "mitm",
) -> None:
    event_queue.put(
        {
            "type": "traffic",
            "source": source,
            "createdAt": datetime.now().isoformat(timespec="seconds"),
            "timestamp": time.time(),
            "uploadBytes": max(0, int(upload_bytes)),
            "downloadBytes": max(0, int(download_bytes)),
            "host": urlparse(url).netloc,
        }
    )
