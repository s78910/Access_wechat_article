from __future__ import annotations

import json
import tempfile
import time
import unittest
from queue import Empty, Queue
from pathlib import Path
from typing import Any
from unittest.mock import patch

import src.workers.article_capture as article_capture
from src.modules.detail.article_detail import ArticleDetailFetchError
from src.modules.storage.sqlite_store import SQLiteStore
from src.workers.article_capture import (
    ArticleArchiveError,
    build_failed_public_article_record,
    build_mitm_timeout_reason,
    build_local_article_archive,
    build_public_article_record,
    collect_article_capture_report_from_mitm,
    extract_article_detail_stats_from_html,
    extract_article_ip_from_html,
    is_report_ready_for_article_storage,
    write_current_mitm_target_probe,
    resolve_mitm_capture_timeout_seconds,
    run_article_capture_worker,
)
from src.modules.proxy.mitm_capture_waiter import (
    article_capture_report_from_mitm_event,
    extract_account_name_from_html_text,
)
from src.modules.storage.article_archive_store import build_record_type_from_selections
from src.workers.mitm_worker import WeChatCaptureAddon, is_article_main_html_url
from src.core.config import ProxyConfig


EXPECTED_ARTICLE_DETAIL_FIELDS = {
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
}


class FakeHomeWindow:
    def __init__(self, hwnd: int = 100) -> None:
        self.NativeWindowHandle = hwnd


class ArticleCaptureMitmArchiveTest(unittest.TestCase):
    def test_mitm_fallback_account_name_ignores_miniprogram_placeholder(self) -> None:
        html_text = """
        <html><head>
          <meta name="author" content="data-miniprogram-nickname">
        </head><body>
          <a id="js_name">新华社</a>
        </body></html>
        """

        self.assertEqual(extract_account_name_from_html_text(html_text), "新华社")

    def test_mitm_event_report_uses_real_account_name_when_meta_author_is_placeholder(self) -> None:
        event = build_mitm_capture_event("https://mp.weixin.qq.com/s/realAccountShort123")
        event["html_text"] = """
        <html><head>
          <meta name="author" content="data-miniprogram-nickname">
        </head><body>
          <a id="js_name">新华社</a>
          <script>
            var msg_title = 'worker测试文章';
            var publish_time = '2026-06-18 18:58';
          </script>
        </body></html>
        """

        report = article_capture_report_from_mitm_event(event, {}, article_index=1)

        self.assertEqual(report["storage"]["account_name"], "新华社")
        self.assertEqual(report["article_detail"]["account_name"], "新华社")

    def test_record_type_from_selections_uses_selected_chinese_names(self) -> None:
        self.assertEqual(
            build_record_type_from_selections({"articleDetail": True, "commentInfo": False}),
            "文章详情",
        )
        self.assertEqual(
            build_record_type_from_selections({"articleDetail": False, "commentInfo": True}),
            "评论信息",
        )
        self.assertEqual(
            build_record_type_from_selections({"articleDetail": True, "commentInfo": True}),
            "文章详情, 评论信息",
        )

    def test_mitm_tls_hooks_emit_article_diagnostics(self) -> None:
        event_queue = Queue()
        capture_queue = Queue()
        addon = WeChatCaptureAddon(
            event_queue=event_queue,
            capture_event_queue=capture_queue,
            store=None,
        )

        addon.tls_clienthello(FakeTlsClientHelloData("mp.weixin.qq.com"))
        addon.tls_established_client(FakeTlsData("mp.weixin.qq.com"))
        addon.tls_failed_client(FakeTlsData("mp.weixin.qq.com", error="unknown ca"))

        diagnostics = drain_queue(capture_queue)
        reasons = [item.get("reason") for item in diagnostics]

        self.assertIn("tls_clienthello", reasons)
        self.assertIn("tls_client_established", reasons)
        self.assertIn("tls_client_failed", reasons)
        self.assertTrue(
            any(item.get("error") == "unknown ca" for item in diagnostics),
            diagnostics,
        )

    def test_keyed_article_query_is_main_html_capture_target_regardless_path(self) -> None:
        self.assertTrue(
            is_article_main_html_url(
                "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret"
            )
        )
        self.assertTrue(
            is_article_main_html_url(
                "https://mp.weixin.qq.com/custom/path?biz=biz&mid=1&idx=1&sn=sn&key=secret"
            )
        )
        self.assertTrue(
            is_article_main_html_url(
                "https://any.weixin.qq.com/custom/path?biz=biz&mid=1&idx=1&sn=sn&key=secret"
            )
        )
        self.assertTrue(
            is_article_main_html_url(
                "https://weixin110.qq.com/custom/path?biz=biz&mid=1&idx=1&sn=sn&key=secret"
            )
        )
        self.assertTrue(
            is_article_main_html_url(
                "https://article-cdn.example.test/custom/path?biz=biz&mid=1&idx=1&sn=sn&key=secret"
            )
        )
        self.assertFalse(
            is_article_main_html_url(
                "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn"
            )
        )
        self.assertFalse(is_article_main_html_url("https://mp.weixin.qq.com/s/shortLink123"))

    def test_proxy_config_payload_keeps_mitm_confdir_and_ssl_insecure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            confdir = Path(temp_dir) / ".mitmproxy"
            payload = ProxyConfig(confdir=confdir, ssl_insecure=True).to_worker_payload()

            self.assertEqual(payload["confdir"], str(confdir))
            self.assertTrue(payload["ssl_insecure"])

    def test_unkeyed_article_html_is_diagnostic_not_main_capture(self) -> None:
        event_queue = Queue()
        capture_queue = Queue()
        addon = WeChatCaptureAddon(
            event_queue=event_queue,
            capture_event_queue=capture_queue,
            store=None,
        )
        flow = FakeHttpFlow(
            "https://mp.weixin.qq.com/s/shortLink123",
            """
            <html>
              <body id="js_article">
                <script>var msg_title = '短链文章'; var publish_time = '2026-06-19 16:20';</script>
                <div id="js_content">正文</div>
              </body>
            </html>
            """,
        )

        addon.response(flow)

        diagnostics = drain_queue(capture_queue)
        self.assertFalse(any(item.get("type") == "article_main_html_captured" for item in diagnostics))
        self.assertTrue(
            any(item.get("reason") == "article_html_without_key_ignored" for item in diagnostics),
            diagnostics,
        )

    def test_mitm_request_hook_emits_referer_article_url_as_fallback_source(self) -> None:
        event_queue = Queue()
        capture_queue = Queue()
        addon = WeChatCaptureAddon(
            event_queue=event_queue,
            capture_event_queue=capture_queue,
            store=None,
        )
        referer_url = "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret"
        flow = FakeHttpFlow("https://mp.weixin.qq.com/mp/geticon?biz=biz&mid=1&idx=1", "")
        flow.request.headers["referer"] = referer_url

        addon.request(flow)

        events = drain_queue(capture_queue)
        requested = [item for item in events if item.get("type") == "article_main_html_requested"]
        self.assertEqual(len(requested), 1, events)
        self.assertEqual(requested[0]["url"], referer_url)
        self.assertEqual(requested[0]["url_source"], "referer")
        self.assertEqual(requested[0]["carrier_url_redacted"], "https://mp.weixin.qq.com/mp/geticon?biz=biz&mid=1&idx=1")
        self.assertTrue(
            any(
                item.get("reason") == "article_referer_seen"
                and item.get("url_redacted") == "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn"
                for item in events
            ),
            events,
        )

    def test_mitm_request_hook_emits_requested_event_only_for_real_keyed_article_request(self) -> None:
        event_queue = Queue()
        capture_queue = Queue()
        addon = WeChatCaptureAddon(
            event_queue=event_queue,
            capture_event_queue=capture_queue,
            store=None,
        )
        url = "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret"
        flow = FakeHttpFlow(url, "")

        addon.request(flow)

        events = drain_queue(capture_queue)
        requested = [item for item in events if item.get("type") == "article_main_html_requested"]
        self.assertEqual(len(requested), 1, events)
        self.assertEqual(requested[0]["url"], url)
        self.assertEqual(requested[0]["url_source"], "request")

        status_events = drain_queue(event_queue)
        auth_events = [item for item in status_events if item.get("type") == "auth_status"]
        self.assertEqual(len(auth_events), 1, status_events)
        self.assertTrue(auth_events[0]["hasKeyUrl"])
        self.assertEqual(auth_events[0]["statusLabel"], "已获取鉴权")
        self.assertNotIn("secret", auth_events[0]["urlRedacted"])

    def test_mitm_request_hook_reports_article_identity_without_key(self) -> None:
        event_queue = Queue()
        capture_queue = Queue()
        addon = WeChatCaptureAddon(
            event_queue=event_queue,
            capture_event_queue=capture_queue,
            store=None,
        )
        flow = FakeHttpFlow("https://weixin110.qq.com/custom?biz=biz&mid=1&idx=1&sn=sn", "")

        addon.request(flow)

        events = drain_queue(capture_queue)
        self.assertTrue(
            any(item.get("reason") == "article_identity_without_key" for item in events),
            events,
        )

    def test_mitm_response_reports_article_html_title_when_seen_on_non_keyed_url(self) -> None:
        event_queue = Queue()
        capture_queue = Queue()
        addon = WeChatCaptureAddon(
            event_queue=event_queue,
            capture_event_queue=capture_queue,
            store=None,
        )
        flow = FakeHttpFlow(
            "https://mp.weixin.qq.com/s/shortLink123",
            """
            <html>
              <body id="js_article">
                <script>
                  var msg_title = '目标文章标题';
                  var publish_time = '2026-06-19 16:20';
                </script>
                <div id="js_content">目标文章正文</div>
              </body>
            </html>
            """,
        )

        addon.response(flow)

        diagnostics = drain_queue(capture_queue)
        matched = [
            item
            for item in diagnostics
            if item.get("reason") == "article_html_without_key_ignored"
        ]
        self.assertEqual(len(matched), 1, diagnostics)
        self.assertEqual(matched[0].get("title"), "目标文章标题")
        self.assertTrue(matched[0].get("title_matched"))

    def test_mitm_response_scans_article_html_on_non_mp_wechat_domain(self) -> None:
        event_queue = Queue()
        capture_queue = Queue()
        addon = WeChatCaptureAddon(
            event_queue=event_queue,
            capture_event_queue=capture_queue,
            store=None,
        )
        flow = FakeHttpFlow(
            "https://channels.weixin.qq.com/article/render?id=abc",
            """
            <html>
              <body id="js_article">
                <h1 id="activity-name">跨域文章标题</h1>
                <script>var publish_time = '2026-06-19 16:20';</script>
                <div id="js_content">跨域文章正文</div>
              </body>
            </html>
            """,
        )

        addon.response(flow)

        diagnostics = drain_queue(capture_queue)
        matched = [
            item
            for item in diagnostics
            if item.get("reason") == "article_html_without_key_ignored"
        ]
        self.assertEqual(len(matched), 1, diagnostics)
        self.assertEqual(matched[0].get("title"), "跨域文章标题")

    def test_mitm_response_reports_title_candidate_from_wechat_json_response(self) -> None:
        event_queue = Queue()
        capture_queue = Queue()
        addon = WeChatCaptureAddon(
            event_queue=event_queue,
            capture_event_queue=capture_queue,
            store=None,
        )
        flow = FakeHttpFlow(
            "https://mp.weixin.qq.com/cgi-bin/appmsg?action=list",
            '{"title":"目标文章标题","items":[]}',
        )
        flow.response.headers["content-type"] = "application/json; charset=utf-8"

        addon.response(flow)

        diagnostics = drain_queue(capture_queue)
        matched = [
            item
            for item in diagnostics
            if item.get("reason") == "wechat_response_title_candidate"
        ]
        self.assertEqual(len(matched), 1, diagnostics)
        self.assertEqual(matched[0].get("title"), "目标文章标题")
        self.assertIn("目标文章标题", matched[0].get("title_candidates") or [])

    def test_mitm_response_reports_target_title_when_plain_body_contains_clicked_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            probe_path = Path(temp_dir) / "current_target.json"
            write_current_mitm_target_probe(
                probe_path,
                article_index=1,
                target_title="点击文章标题",
            )
            event_queue = Queue()
            capture_queue = Queue()
            addon = WeChatCaptureAddon(
                event_queue=event_queue,
                capture_event_queue=capture_queue,
                store=None,
                target_probe_path=probe_path,
            )
            flow = FakeHttpFlow(
                "https://res.wx.qq.com/t/wx_fed/page-frame/data?id=abc",
                "这里不是标准文章 HTML，也没有 title 字段，但正文里出现了点击文章标题。",
            )
            flow.response.headers["content-type"] = "text/plain; charset=utf-8"

            addon.response(flow)

            diagnostics = drain_queue(capture_queue)
            matched = [
                item
                for item in diagnostics
                if item.get("reason") == "wechat_response_target_title_seen"
            ]
            self.assertEqual(len(matched), 1, diagnostics)
            self.assertEqual(matched[0].get("title"), "点击文章标题")
            self.assertTrue(matched[0].get("title_matched"))

    def test_mitm_title_matched_response_reports_runtime_params_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            probe_path = Path(temp_dir) / "current_target.json"
            write_current_mitm_target_probe(
                probe_path,
                article_index=1,
                target_title="点击文章标题",
            )
            event_queue = Queue()
            capture_queue = Queue()
            addon = WeChatCaptureAddon(
                event_queue=event_queue,
                capture_event_queue=capture_queue,
                store=None,
                target_probe_path=probe_path,
            )
            body = (
                '{"title":"点击文章标题","__biz":"biz-from-body","pass_ticket":"ticket-secret",'
                '"key":"key-secret","appmsg_token":"token-secret","mid":"123","idx":"1","sn":"sn-value"}'
            )
            flow = FakeHttpFlow(
                "https://mp.weixin.qq.com/mp/tts?action=getttslistenitem&__biz=biz-from-url&appmsgid=123&idx=1",
                body,
            )
            flow.response.headers["content-type"] = "application/json; charset=utf-8"

            addon.response(flow)

            diagnostics = drain_queue(capture_queue)
            matched = [
                item
                for item in diagnostics
                if item.get("reason") == "wechat_response_target_title_seen"
            ]
            self.assertEqual(len(matched), 1, diagnostics)
            runtime_params = matched[0].get("runtime_params") or {}
            self.assertIn("__biz", runtime_params)
            self.assertIn("pass_ticket", runtime_params)
            self.assertIn("key", runtime_params)
            self.assertIn("appmsg_token", runtime_params)
            self.assertEqual(runtime_params["__biz"]["value"], "biz-from-body")
            self.assertEqual(runtime_params["pass_ticket"]["value_redacted"], "tic...cret")
            self.assertEqual(runtime_params["key"]["value_redacted"], "key...cret")
            self.assertEqual(runtime_params["appmsg_token"]["value_redacted"], "tok...cret")
            self.assertEqual(runtime_params["key"]["source"], "response_body")

    def test_mitm_five_second_probe_records_response_matching_clicked_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            probe_path = Path(temp_dir) / "current_target.json"
            write_current_mitm_target_probe(
                probe_path,
                article_index=1,
                target_title="clicked title",
                inspect_duration_seconds=5,
            )
            event_queue = Queue()
            capture_queue = Queue()
            addon = WeChatCaptureAddon(
                event_queue=event_queue,
                capture_event_queue=capture_queue,
                store=None,
                target_probe_path=probe_path,
            )
            body = '{"title":"clicked title","biz":"body-biz","pass_ticket":"ticket-secret"}'
            flow = FakeHttpFlow(
                "https://mp.weixin.qq.com/mp/tts?action=getttslistenitem&__biz=url-biz&appmsgid=123&idx=1",
                body,
            )
            flow.response.headers["content-type"] = "application/json; charset=utf-8"

            addon.response(flow)

            diagnostics = drain_queue(capture_queue)
            matched = [
                item
                for item in diagnostics
                if item.get("reason") == "realtime_response_title_match"
            ]
            self.assertEqual(len(matched), 1, diagnostics)
            self.assertEqual(matched[0].get("title"), "clicked title")
            self.assertEqual(matched[0].get("probe_window_seconds"), 5)
            self.assertEqual(matched[0].get("request_url_redacted"), matched[0].get("url_redacted"))
            runtime_params = matched[0].get("runtime_params") or {}
            self.assertEqual(runtime_params["biz"]["value"], "body-biz")
            self.assertEqual(runtime_params["pass_ticket"]["source"], "response_body")

    def test_empty_click_title_clears_stale_mitm_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            probe_path = Path(temp_dir) / "current_target.json"
            write_current_mitm_target_probe(
                probe_path,
                article_index=1,
                target_title="旧文章标题",
                inspect_duration_seconds=5,
            )

            write_current_mitm_target_probe(
                probe_path,
                article_index=1,
                target_title="",
                inspect_duration_seconds=5,
            )

            self.assertFalse(probe_path.exists())

    def test_mitm_five_second_probe_reports_large_response_not_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            probe_path = Path(temp_dir) / "current_target.json"
            write_current_mitm_target_probe(
                probe_path,
                article_index=1,
                target_title="clicked title",
                inspect_duration_seconds=5,
            )
            event_queue = Queue()
            capture_queue = Queue()
            addon = WeChatCaptureAddon(
                event_queue=event_queue,
                capture_event_queue=capture_queue,
                store=None,
                target_probe_path=probe_path,
            )
            flow = FakeHttpFlow(
                "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn",
                "small body",
            )
            flow.response.headers["content-type"] = "text/html; charset=utf-8"
            flow.response.raw_content = b"x" * (1_000_001)

            addon.response(flow)

            diagnostics = drain_queue(capture_queue)
            matched = [
                item
                for item in diagnostics
                if item.get("reason") == "realtime_response_body_too_large"
            ]
            self.assertEqual(len(matched), 1, diagnostics)
            self.assertEqual(matched[0].get("body_chars"), 1_000_001)

    def test_mitm_idle_with_probe_path_does_not_queue_capture_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            probe_path = Path(temp_dir) / "current_target.json"
            event_queue = Queue()
            capture_queue = Queue()
            addon = WeChatCaptureAddon(
                event_queue=event_queue,
                capture_event_queue=capture_queue,
                store=None,
                target_probe_path=probe_path,
            )
            flow = FakeHttpFlow(
                "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret",
                "<html><body id='js_article'><script>var msg_title='空闲文章';</script></body></html>",
            )

            addon.request(flow)
            addon.response(flow)
            addon.tls_failed_client(FakeTlsData("mp.weixin.qq.com", error="unknown ca"))

            self.assertEqual(drain_queue(capture_queue), [])

    def test_mitm_active_probe_path_keeps_queueing_capture_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            probe_path = Path(temp_dir) / "current_target.json"
            write_current_mitm_target_probe(
                probe_path,
                article_index=1,
                target_title="有效探针文章",
                inspect_duration_seconds=5,
            )
            event_queue = Queue()
            capture_queue = Queue()
            addon = WeChatCaptureAddon(
                event_queue=event_queue,
                capture_event_queue=capture_queue,
                store=None,
                target_probe_path=probe_path,
            )
            flow = FakeHttpFlow(
                "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret",
                "<html><body id='js_article'><script>var msg_title='有效探针文章';</script></body></html>",
            )

            addon.request(flow)
            addon.response(flow)

            events = drain_queue(capture_queue)
            self.assertTrue(any(item.get("type") == "article_main_html_requested" for item in events), events)
            self.assertTrue(any(item.get("type") == "article_main_html_captured" for item in events), events)

    def test_extract_article_ip_from_wechat_ip_wording_object(self) -> None:
        html_text = """
        <script>
          window.ip_wording = {
            countryName: '中国',
            provinceName: '北京',
            cityName: ''
          };
          window.show_ip_wording = '1' * 1;
        </script>
        """

        self.assertEqual(extract_article_ip_from_html(html_text), "北京")

    def test_extract_article_ip_ignores_show_ip_wording_flag(self) -> None:
        html_text = "<script>window.show_ip_wording = '1' * 1;</script>"

        self.assertIsNone(extract_article_ip_from_html(html_text))

    def test_extract_article_stats_from_wechat_js_object_values(self) -> None:
        html_text = """
        <script>
          var appmsgBarData = {
            old_like_count: '6006' * 1,
            share_count: '33513' * 1,
            like_count: '2450' * 1,
            comment_count: '11' * 1,
            read_num: '100001' * 1,
            tts_heard_person_cnt: '2998' * 1
          };
        </script>
        """

        stats = extract_article_detail_stats_from_html(html_text)

        self.assertEqual(stats["audience_count"], 2998)
        self.assertEqual(stats["read_count"], 100001)
        self.assertEqual(stats["like_count"], 6006)
        self.assertEqual(stats["share_count"], 33513)
        self.assertEqual(stats["recommend_count"], 2450)
        self.assertEqual(stats["comment_count"], 11)

    def test_archive_from_mitm_keeps_only_request_html_and_detail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_html = root / "captured.html"
            source_html.write_text(
                """
                <html>
                  <head><meta property="og:url" content="https://mp.weixin.qq.com/s/testShort123"></head>
                  <body>
                    <script>
                      var msg_title = '今晚，油价调整';
                      var publish_time = '2026-06-18 18:58';
                      window.short_link = 'https://mp.weixin.qq.com/s/testShort123';
                      var ip_wording = '发表于北京';
                    </script>
                    <div id="js_content">正文内容</div>
                  </body>
                </html>
                """,
                encoding="utf-8",
            )
            request_context = root / "request.json"
            request_context.write_text(
                json.dumps(
                    {
                        "method": "GET",
                        "request_url": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret",
                        "request_headers": {"user-agent": "MicroMessenger"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            report = {
                "created_at": "2026-06-18 19:00:00",
                "storage": {"account_name": "测试公众号", "title": "今晚，油价调整"},
                "main_html_capture": {
                    "url": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret",
                    "url_redacted": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn",
                    "private_html_path": str(source_html),
                    "request_context_file": str(request_context),
                    "captured_time": "2026-06-18 19:00:00",
                    "status_code": 200,
                    "response_headers": {"content-type": "text/html"},
                },
                "article_detail": {
                    "account_name": "测试公众号",
                    "article_title": "今晚，油价调整",
                    "published_article_time": "2026-06-18 18:58",
                    "article_short_link": "https://mp.weixin.qq.com/s/testShort123",
                    "html_text": source_html.read_text(encoding="utf-8"),
                },
            }

            def fake_detail_fetcher(_url: str, **_kwargs):
                raise AssertionError("MITM 已有 response HTML 时不应重新请求带 key URL")

            archive = build_local_article_archive(
                report,
                article_index=1,
                selections={"articleDetail": True},
                storage_root=root / "storages",
                detail_fetcher=fake_detail_fetcher,
            )

            archive_dir = Path(archive["storage_dir"])
            detail_path = archive_dir / "article_detail.json"
            detail = json.loads(detail_path.read_text(encoding="utf-8"))
            record = build_public_article_record(archive)

            self.assertEqual(detail["account_name"], "测试公众号")
            self.assertEqual(detail["article_title"], "今晚，油价调整")
            self.assertEqual(detail["short_link"], "https://mp.weixin.qq.com/s/testShort123")
            self.assertEqual(set(detail), EXPECTED_ARTICLE_DETAIL_FIELDS)
            self.assertEqual(record["record_type"], "文章详情")
            self.assertEqual(record["article_link"], "https://mp.weixin.qq.com/s/testShort123")
            self.assertFalse((archive_dir / "temporary_request").exists())
            self.assertFalse((archive_dir / "index.html").exists())
            self.assertFalse((archive_dir / "assets").exists())
            self.assertNotIn("offline_page", detail)

    def test_archive_fetches_comments_after_article_detail_when_selected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_html = root / "captured.html"
            source_html.write_text(
                """
                <html><body>
                  <script>
                    var nickname = '测试公众号';
                    var msg_title = '带评论文章';
                    var publish_time = '2026-06-19 21:39';
                    var short_link = 'https://mp.weixin.qq.com/s/commentShort123';
                    var comment_id = 'comment-id';
                    var appmsg_token = 'token-value';
                  </script>
                </body></html>
                """,
                encoding="utf-8",
            )
            report = {
                "created_at": "2026-06-19 22:00:00",
                "storage": {"account_name": "测试公众号", "title": "带评论文章"},
                "main_html_capture": {
                    "url": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret&pass_ticket=ticket",
                    "url_redacted": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn",
                    "private_html_path": str(source_html),
                    "request_headers": {
                        "user-agent": "MicroMessenger/8.0",
                        "cookie": "wxuin=777",
                        "x-requested-with": "com.tencent.mm",
                    },
                },
                "article_detail": {"html_text": source_html.read_text(encoding="utf-8")},
            }
            captured: dict[str, object] = {}

            def fake_comment_fetcher(*args, **kwargs):
                captured["args"] = args
                captured["kwargs"] = kwargs
                article_dir = Path(args[2])
                comment_path = article_dir / "comments_final.json"
                comment_path.write_text(
                    json.dumps({"summary": {"top_level_comment_count": 1, "reply_count": 0}, "comments": []}, ensure_ascii=False),
                    encoding="utf-8",
                )
                return {
                    "attempted": True,
                    "ok": True,
                    "comments_final_json_path": str(comment_path),
                    "comment_count": 1,
                    "reply_count": 0,
                }

            archive = build_local_article_archive(
                report,
                article_index=1,
                selections={"articleDetail": True, "commentInfo": True},
                storage_root=root / "storages",
                comment_fetcher=fake_comment_fetcher,
            )
            record = build_public_article_record(archive)

            archive_dir = Path(archive["storage_dir"])
            self.assertEqual(captured["args"][0], "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret&pass_ticket=ticket")
            self.assertEqual(Path(captured["args"][2]), archive_dir)
            self.assertEqual(captured["kwargs"]["request_headers"]["user-agent"], "MicroMessenger/8.0")
            self.assertEqual(captured["kwargs"]["collect_time"], "2026-06-19 22:00:00")
            self.assertTrue(captured["kwargs"]["download_resources"])
            self.assertFalse(captured["kwargs"]["download_avatars"])
            self.assertTrue(captured["kwargs"]["download_emojis"])
            self.assertTrue(captured["kwargs"]["download_pictures"])
            self.assertEqual(captured["kwargs"]["page_pause_seconds"], 0)
            self.assertEqual(captured["kwargs"]["reply_page_pause_seconds"], 0)
            self.assertEqual(report["comment_fetch"]["comment_count"], 1)
            self.assertEqual(archive["comment_fetch"]["comments_final_json_path"], str(archive_dir / "comments_final.json"))
            self.assertEqual(record["record_type"], "文章详情, 评论信息")

    def test_archive_skips_comments_when_comment_info_not_selected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_html = root / "captured.html"
            source_html.write_text(
                """
                <html><body>
                  <script>
                    var nickname = '测试公众号';
                    var msg_title = '不抓评论文章';
                    var publish_time = '2026-06-19 21:39';
                    var short_link = 'https://mp.weixin.qq.com/s/noCommentShort123';
                  </script>
                </body></html>
                """,
                encoding="utf-8",
            )
            report = {
                "created_at": "2026-06-19 22:00:00",
                "storage": {"account_name": "测试公众号", "title": "不抓评论文章"},
                "main_html_capture": {
                    "url": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret",
                    "private_html_path": str(source_html),
                    "request_headers": {"user-agent": "MicroMessenger/8.0"},
                },
                "article_detail": {"html_text": source_html.read_text(encoding="utf-8")},
            }

            def fake_comment_fetcher(*_args, **_kwargs):
                raise AssertionError("未勾选评论信息时不应请求评论接口")

            archive = build_local_article_archive(
                report,
                article_index=1,
                selections={"articleDetail": True, "commentInfo": False},
                storage_root=root / "storages",
                comment_fetcher=fake_comment_fetcher,
            )

            self.assertEqual(archive["comment_fetch"]["reason"], "comment_info_not_selected")
            self.assertFalse((Path(archive["storage_dir"]) / "comments_final.json").exists())

    def test_archive_uses_requests_fallback_only_for_referer_keyed_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            captured_headers: dict[str, object] = {}
            report = {
                "created_at": "2026-06-18 19:00:00",
                "storage": {"account_name": "测试公众号", "title": "今晚，油价调整"},
                "main_html_capture": {
                    "url": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret",
                    "url_redacted": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn",
                    "request_headers": {
                        "user-agent": "MicroMessenger/8.0",
                        "cookie": "wxuin=abc",
                        "sec-fetch-site": "same-origin",
                    },
                    "source": "mitm_referer_fallback",
                    "url_source": "referer",
                },
                "article_detail": {},
            }

            def fake_detail_fetcher(url: str, **kwargs):
                captured_headers["url"] = url
                captured_headers["headers"] = kwargs.get("request_headers")
                detail = build_fake_article_detail("https://mp.weixin.qq.com/s/fallbackShort123")
                detail["article_title"] = "今晚，油价调整"
                return detail

            archive = build_local_article_archive(
                report,
                article_index=1,
                selections={"articleDetail": True},
                storage_root=root / "storages",
                detail_fetcher=fake_detail_fetcher,
            )

            detail = json.loads(Path(archive["article_detail_path"]).read_text(encoding="utf-8"))
            self.assertEqual(captured_headers["url"], "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret")
            self.assertEqual(
                captured_headers["headers"],
                {
                    "user-agent": "MicroMessenger/8.0",
                    "cookie": "wxuin=abc",
                    "sec-fetch-site": "same-origin",
                },
            )
            self.assertEqual(detail["short_link"], "https://mp.weixin.qq.com/s/fallbackShort123")

    def test_archive_rejects_referer_fallback_when_detail_title_does_not_match_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = {
                "created_at": "2026-06-18 19:00:00",
                "storage": {"account_name": "测试公众号", "title": "主页识别标题"},
                "target_article": {"title": "主页识别标题"},
                "main_html_capture": {
                    "url": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret",
                    "request_headers": {"user-agent": "MicroMessenger/8.0"},
                    "source": "mitm_referer_fallback",
                    "url_source": "referer",
                },
                "article_detail": {},
            }

            def fake_detail_fetcher(_url: str, **_kwargs):
                detail = build_fake_article_detail("https://mp.weixin.qq.com/s/wrongTitleShort123")
                detail["article_title"] = "其他文章标题"
                return detail

            with self.assertRaisesRegex(ArticleArchiveError, "标题"):
                build_local_article_archive(
                    report,
                    article_index=1,
                    selections={"articleDetail": True},
                    storage_root=root / "storages",
                    detail_fetcher=fake_detail_fetcher,
                )

    def test_archive_uses_requests_fallback_for_request_stage_keyed_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            captured: dict[str, object] = {}
            report = {
                "created_at": "2026-06-18 19:00:00",
                "storage": {"account_name": "测试公众号", "title": "request 阶段文章"},
                "target_article": {"title": "request 阶段文章"},
                "main_html_capture": {
                    "url": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret",
                    "request_headers": {"user-agent": "MicroMessenger/8.0"},
                    "source": "mitm_keyed_url_fallback",
                    "url_source": "request",
                },
                "article_detail": {},
            }

            def fake_detail_fetcher(url: str, **kwargs):
                captured["url"] = url
                captured["headers"] = kwargs.get("request_headers")
                detail = build_fake_article_detail("https://mp.weixin.qq.com/s/requestFallbackShort123")
                detail["article_title"] = "request 阶段文章"
                return detail

            archive = build_local_article_archive(
                report,
                article_index=1,
                selections={"articleDetail": True},
                storage_root=root / "storages",
                detail_fetcher=fake_detail_fetcher,
            )

            self.assertEqual(captured["url"], "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret")
            self.assertEqual(captured["headers"], {"user-agent": "MicroMessenger/8.0"})
            detail = json.loads(Path(archive["article_detail_path"]).read_text(encoding="utf-8"))
            self.assertEqual(detail["short_link"], "https://mp.weixin.qq.com/s/requestFallbackShort123")

    def test_archive_passes_requests_fallback_html_to_comment_fetcher(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fallback_html = """
            <html><body>
              <script>
                var nickname = '测试公众号';
                var msg_title = 'Referer 保底评论文章';
                var publish_time = '2026-06-19 22:42';
                var short_link = 'https://mp.weixin.qq.com/s/fallbackCommentShort123';
                var comment_id = 'comment-from-fallback-html';
              </script>
            </body></html>
            """
            captured: dict[str, object] = {}
            report = {
                "created_at": "2026-06-20 00:25:16",
                "storage": {"account_name": "测试公众号", "title": "Referer 保底评论文章"},
                "main_html_capture": {
                    "url": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret",
                    "request_headers": {"user-agent": "MicroMessenger/8.0"},
                    "source": "mitm_referer_fallback",
                },
                "article_detail": {},
            }

            def fake_detail_fetcher(_url: str, **_kwargs):
                detail = build_fake_article_detail("https://mp.weixin.qq.com/s/fallbackCommentShort123")
                detail["article_title"] = "Referer 保底评论文章"
                detail["_source_html"] = fallback_html
                return detail

            def fake_comment_fetcher(_url: str, html_text: str, article_dir: Path, **_kwargs):
                captured["html_text"] = html_text
                comment_path = Path(article_dir) / "comments_final.json"
                comment_path.write_text(
                    json.dumps({"summary": {"top_level_comment_count": 0}, "comments": []}, ensure_ascii=False),
                    encoding="utf-8",
                )
                return {
                    "attempted": True,
                    "ok": True,
                    "comments_final_json_path": str(comment_path),
                    "comment_count": 0,
                    "reply_count": 0,
                }

            archive = build_local_article_archive(
                report,
                article_index=1,
                selections={"articleDetail": True, "commentInfo": True},
                storage_root=root / "storages",
                detail_fetcher=fake_detail_fetcher,
                comment_fetcher=fake_comment_fetcher,
            )

            self.assertIn("comment-from-fallback-html", str(captured["html_text"]))
            self.assertTrue((Path(archive["storage_dir"]) / "comments_final.json").exists())
            saved_detail = json.loads(Path(archive["article_detail_path"]).read_text(encoding="utf-8"))
            self.assertNotIn("_source_html", saved_detail)

    def test_archive_replaces_unreadable_window_placeholder_with_html_account_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_html = root / "captured.html"
            source_html.write_text(
                """
                <html><body>
                  <script>
                    var nickname = '人民日报';
                    var msg_title = '真实文章标题';
                    var publish_time = '2026-06-19 18:20';
                    var short_link = 'https://mp.weixin.qq.com/s/realShort123';
                  </script>
                </body></html>
                """,
                encoding="utf-8",
            )
            report = {
                "created_at": "2026-06-19 18:21:00",
                "storage": {
                    "account_name": "已检测到公众号窗口，但无法读取主页内容",
                    "title": "真实文章标题",
                    "article_url": "https://mp.weixin.qq.com/s/realShort123",
                },
                "main_html_capture": {
                    "url": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret",
                    "private_html_path": str(source_html),
                },
                "article_detail": {"html_text": source_html.read_text(encoding="utf-8")},
            }

            def fake_detail_fetcher(_url: str, **_kwargs):
                return {
                    "account_name": "人民日报",
                    "article_title": "真实文章标题",
                    "published_article_time": "2026-06-19 18:20",
                    "short_link": "https://mp.weixin.qq.com/s/realShort123",
                    "url_redacted": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn",
                    "audience_count": None,
                    "read_count": None,
                    "like_count": None,
                    "share_count": None,
                    "recommend_count": None,
                    "comment_count": None,
                    "collect_time": "2026-06-19 18:21:00",
                }

            archive = build_local_article_archive(
                report,
                article_index=1,
                selections={"articleDetail": True},
                storage_root=root / "storages",
                detail_fetcher=fake_detail_fetcher,
            )
            detail = json.loads(Path(archive["article_detail_path"]).read_text(encoding="utf-8"))
            record = build_public_article_record(archive)

            self.assertEqual(detail["account_name"], "人民日报")
            self.assertEqual(record["account_name"], "人民日报")
            self.assertIn("人民日报", archive["storage_dir"])
            self.assertNotIn("无法读取主页内容", archive["storage_dir"])

    def test_archive_prefers_html_account_name_when_window_account_looks_like_content_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_html = root / "captured.html"
            source_html.write_text(
                """
                <html><body>
                  <script>
                    var nickname = '新华社';
                    var msg_title = '真实新闻标题';
                    var publish_time = '2026-06-20 08:09';
                    var short_link = 'https://mp.weixin.qq.com/s/xinhuaRealShort123';
                  </script>
                </body></html>
                """,
                encoding="utf-8",
            )
            report = {
                "created_at": "2026-06-20 08:10:00",
                "storage": {
                    "account_name": "夏至，喜至！",
                    "title": "真实新闻标题",
                    "article_url": "https://mp.weixin.qq.com/s/xinhuaRealShort123",
                },
                "main_html_capture": {
                    "url": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret",
                    "private_html_path": str(source_html),
                },
                "article_detail": {"html_text": source_html.read_text(encoding="utf-8")},
            }

            def fake_detail_fetcher(_url: str, **_kwargs):
                raise AssertionError("MITM 已有 response HTML 时不应重新请求带 key URL")

            archive = build_local_article_archive(
                report,
                article_index=1,
                selections={"articleDetail": True},
                storage_root=root / "storages",
                detail_fetcher=fake_detail_fetcher,
            )
            detail = json.loads(Path(archive["article_detail_path"]).read_text(encoding="utf-8"))
            record = build_public_article_record(archive)

            self.assertEqual(detail["account_name"], "新华社")
            self.assertEqual(report["storage"]["account_name"], "新华社")
            self.assertEqual(record["account_name"], "新华社")
            self.assertIn("新华社", archive["storage_dir"])
            self.assertNotIn("夏至，喜至！", archive["storage_dir"])

    def test_archive_without_short_link_fails_before_detail_or_sqlite_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_html = root / "captured.html"
            source_html.write_text(
                """
                <html><body>
                  <script>
                    var msg_title = '没有短链的文章';
                    var publish_time = '2026-06-18 18:58';
                  </script>
                </body></html>
                """,
                encoding="utf-8",
            )
            report = {
                "created_at": "2026-06-18 19:00:00",
                "storage": {
                    "account_name": "测试公众号",
                    "title": "没有短链的文章",
                    "article_url": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret",
                },
                "main_html_capture": {
                    "url": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret",
                    "private_html_path": str(source_html),
                    "status_code": 200,
                },
                "article_detail": {"html_text": source_html.read_text(encoding="utf-8")},
            }

            def fake_detail_fetcher(_url: str, **_kwargs):
                raise ArticleDetailFetchError("未从文章详情响应中解析到短链接 https://mp.weixin.qq.com/s/xxxx")

            with self.assertRaises(ArticleArchiveError) as context:
                build_local_article_archive(
                    report,
                    article_index=1,
                    selections={"articleDetail": True},
                    storage_root=root / "storages",
                    detail_fetcher=fake_detail_fetcher,
                )

            self.assertIn("未从文章响应中解析到短链接", str(context.exception))
            self.assertFalse(list((root / "storages").glob("**/article_detail.json")))

    def test_worker_writes_sqlite_when_mitm_event_has_short_link(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            event_queue = Queue()
            capture_queue = FakeCaptureQueue(build_mitm_capture_event(short_link="https://mp.weixin.qq.com/s/workerShort1"))

            with patch(
                "src.workers.article_capture.fetch_article_detail_from_keyed_url",
                return_value=build_fake_article_detail("https://mp.weixin.qq.com/s/workerShort1"),
            ):
                run_article_capture_worker(
                    event_queue,
                    {
                        "db_path": str(root / "awa_public.sqlite3"),
                        "storage_root": str(root / "storages"),
                        "output_root": str(root / "captures"),
                        "account_name": "测试公众号",
                        "enable_home_article_click": False,
                        "mitm_capture_timeout_seconds": 1,
                        "run_options": {"recordLimit": 1, "selections": {"articleDetail": True}},
                    },
                    capture_queue,
                )

            store = SQLiteStore(root / "awa_public.sqlite3")
            self.assertEqual(store.count_public_accounts(), 1)
            self.assertEqual(store.count_public_articles(), 1)
            logs = drain_queue(event_queue)
            self.assertTrue(any(item.get("level") == "SUCCESS" and "已保存" in item.get("message", "") for item in logs))

    def test_worker_logs_error_and_skips_sqlite_without_short_link(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            event_queue = Queue()
            capture_queue = FakeCaptureQueue(build_mitm_capture_event(short_link=""))

            with patch(
                "src.workers.article_capture.fetch_article_detail_from_keyed_url",
                side_effect=ArticleDetailFetchError("未从文章详情响应中解析到短链接 https://mp.weixin.qq.com/s/xxxx"),
            ):
                run_article_capture_worker(
                    event_queue,
                    {
                        "db_path": str(root / "awa_public.sqlite3"),
                        "storage_root": str(root / "storages"),
                        "output_root": str(root / "captures"),
                        "account_name": "测试公众号",
                        "enable_home_article_click": False,
                        "mitm_capture_timeout_seconds": 1,
                        "run_options": {"recordLimit": 1, "selections": {"articleDetail": True}},
                    },
                    capture_queue,
                )

            store = SQLiteStore(root / "awa_public.sqlite3")
            self.assertEqual(store.count_public_articles(), 1)
            self.assertFalse(list((root / "storages").glob("**/article_detail.json")))
            with store._connect() as conn:
                latest = conn.execute(
                    "SELECT article_link, collect_status FROM awa_public_articles ORDER BY id DESC LIMIT 1"
                ).fetchone()
            self.assertEqual(latest[1], "failed")
            self.assertEqual(latest[0], "")
            logs = drain_queue(event_queue)
            self.assertTrue(any(item.get("level") == "ERROR" and "未从文章响应中解析到短链接" in item.get("message", "") for item in logs))

    def test_worker_does_not_clear_wechat_cache_or_release_runtime_before_click(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            call_order: list[str] = []

            def release_handles():
                raise AssertionError("采集任务不应释放 WeChatAppEx 运行时进程")

            def clear_cache(_profiles_root=None):
                raise AssertionError("采集任务不应清理微信网页缓存")

            def click_home(_config, _article_index, **_kwargs):
                call_order.append("click")
                return {
                    "ok": True,
                    "target_title": "worker测试文章",
                    "click_result": {"method": "post_message"},
                }

            class FakeCandidate:
                title = "worker测试文章"
                article_index = 1
                rect = (100, 100, 500, 140)
                hwnd = 200

            class FakeCursor:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.items = [FakeCandidate()]

                def next_candidate(self):
                    if not self.items:
                        return None
                    return self.items.pop(0)

            with (
                patch("src.workers.article_capture.release_wechat_web_cache_handles", side_effect=release_handles, create=True),
                patch("src.workers.article_capture.clear_wechat_web_cache", side_effect=clear_cache, create=True),
                patch("src.workers.article_capture.find_wechat_home_window", return_value=FakeHomeWindow()),
                patch("src.workers.article_capture.HomeArticleCursor", FakeCursor),
                patch(
                    "src.workers.article_capture.close_wechat_article_detail_windows",
                    return_value={"ok": True, "closed": [], "skipped": [], "errors": []},
                ),
                patch("src.workers.article_capture.trigger_home_article_open", side_effect=click_home),
                patch(
                    "src.workers.article_capture.fetch_article_detail_from_keyed_url",
                    return_value=build_fake_article_detail("https://mp.weixin.qq.com/s/workerShort1"),
                ),
            ):
                run_article_capture_worker(
                    Queue(),
                    {
                        "db_path": str(root / "awa_public.sqlite3"),
                        "storage_root": str(root / "storages"),
                        "account_name": "测试公众号",
                        "enable_home_article_click": True,
                        "mitm_capture_timeout_seconds": 1,
                        "run_options": {"recordLimit": 1, "selections": {"articleDetail": True}},
                    },
                    FakeCaptureQueue(build_mitm_capture_event(short_link="https://mp.weixin.qq.com/s/workerShort1")),
                )

            self.assertEqual(call_order, ["click"])

    def test_worker_ignores_runtime_release_config_before_click(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            call_order: list[str] = []

            def release_handles():
                raise AssertionError("采集任务不应释放 WeChatAppEx 运行时进程")

            def clear_cache(_profiles_root=None):
                raise AssertionError("采集任务不应清理微信网页缓存")

            def click_home(_config, _article_index, **_kwargs):
                call_order.append("click")
                return {
                    "ok": True,
                    "target_title": "worker测试文章",
                    "click_result": {"method": "post_message"},
                }

            class FakeCandidate:
                title = "worker测试文章"
                article_index = 1
                rect = (100, 100, 500, 140)
                hwnd = 200

            class FakeCursor:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.items = [FakeCandidate()]

                def next_candidate(self):
                    if not self.items:
                        return None
                    return self.items.pop(0)

            with (
                patch("src.workers.article_capture.release_wechat_web_cache_handles", side_effect=release_handles, create=True),
                patch("src.workers.article_capture.clear_wechat_web_cache", side_effect=clear_cache, create=True),
                patch("src.workers.article_capture.find_wechat_home_window", return_value=FakeHomeWindow()),
                patch("src.workers.article_capture.HomeArticleCursor", FakeCursor),
                patch(
                    "src.workers.article_capture.close_wechat_article_detail_windows",
                    return_value={"ok": True, "closed": [], "skipped": [], "errors": []},
                ),
                patch("src.workers.article_capture.trigger_home_article_open", side_effect=click_home),
                patch(
                    "src.workers.article_capture.fetch_article_detail_from_keyed_url",
                    return_value=build_fake_article_detail("https://mp.weixin.qq.com/s/workerShort1"),
                ),
            ):
                run_article_capture_worker(
                    Queue(),
                    {
                        "db_path": str(root / "awa_public.sqlite3"),
                        "storage_root": str(root / "storages"),
                        "account_name": "测试公众号",
                        "enable_home_article_click": True,
                        "release_wechat_web_runtime_before_click": True,
                        "mitm_capture_timeout_seconds": 1,
                        "run_options": {"recordLimit": 1, "selections": {"articleDetail": True}},
                    },
                    FakeCaptureQueue(build_mitm_capture_event(short_link="https://mp.weixin.qq.com/s/workerShort1")),
                )

            self.assertEqual(call_order, ["click"])


    def test_worker_skips_saved_title_and_clicks_next_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "awa_public.sqlite3"
            store = SQLiteStore(db_path)
            store.save_public_article(
                {
                    "account_name": "account-a",
                    "article_title": "existing title",
                    "published_article_time": "2026-06-18 18:00",
                    "article_link": "https://mp.weixin.qq.com/s/existing-title",
                    "record_type": "article-detail",
                    "collect_time": "2026-06-18 18:01:00",
                    "collect_status": "saved",
                }
            )
            clicked_indices: list[int] = []

            class FakeCandidate:
                def __init__(self, title: str, article_index: int) -> None:
                    self.title = title
                    self.article_index = article_index
                    self.rect = (100, 100, 500, 140)
                    self.hwnd = 200

            class FakeCursor:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.items = [FakeCandidate("existing title", 1), FakeCandidate("new title", 2)]

                def next_candidate(self):
                    if not self.items:
                        return None
                    return self.items.pop(0)

            def click_home(_config, article_index, **_kwargs):
                clicked_indices.append(article_index)
                before_click = _kwargs.get("before_click")
                if callable(before_click):
                    before_click(FakeCandidate("new title", article_index))
                return {
                    "ok": True,
                    "target_title": "new title",
                    "click_result": {"method": "post_message"},
                }

            detail = build_fake_article_detail("https://mp.weixin.qq.com/s/new-title")
            detail["article_title"] = "new title"
            with (
                patch("src.workers.article_capture.find_wechat_home_window", return_value=FakeHomeWindow()),
                patch("src.workers.article_capture.HomeArticleCursor", FakeCursor),
                patch(
                    "src.workers.article_capture.close_wechat_article_detail_windows",
                    return_value={"ok": True, "closed": [], "skipped": [], "errors": []},
                ),
                patch("src.workers.article_capture.trigger_home_article_open", side_effect=click_home),
                patch("src.workers.article_capture.fetch_article_detail_from_keyed_url", return_value=detail),
            ):
                event_queue = Queue()
                run_article_capture_worker(
                    event_queue,
                    {
                        "db_path": str(db_path),
                        "storage_root": str(root / "storages"),
                        "account_name": "account-a",
                        "enable_home_article_click": True,
                        "mitm_capture_timeout_seconds": 1,
                        "run_options": {"recordLimit": 1, "selections": {"articleDetail": True}},
                    },
                    FakeCaptureQueue(build_mitm_capture_event(short_link="https://mp.weixin.qq.com/s/new-title")),
                )

            self.assertEqual(clicked_indices, [2])
            self.assertEqual(store.count_public_articles(), 2)
            logs = drain_queue(event_queue)
            self.assertTrue(any("已存在，跳过" in item.get("message", "") for item in logs), logs)

    def test_flow_closes_detail_window_after_each_processed_article_even_when_legacy_interval_config_exists(self) -> None:
        from src.workers.article_capture_flow import ArticleCaptureDependencies, run_article_capture_flow

        call_order: list[str] = []

        class FakeCandidate:
            def __init__(self, title: str, article_index: int) -> None:
                self.title = title
                self.article_index = article_index
                self.rect = (100, 100, 500, 140)
                self.hwnd = 200

        class FakeCursor:
            def __init__(self, *_args, **_kwargs) -> None:
                self.items = [FakeCandidate("first", 1), FakeCandidate("second", 2)]

            def next_candidate(self):
                if not self.items:
                    return None
                return self.items.pop(0)

            def invalidate(self) -> None:
                pass

        class FakeStore:
            def has_saved_public_article_title(self, _account_name: str, _title: str) -> bool:
                return False

            def save_public_article(self, _record: dict) -> None:
                call_order.append("save")

        def open_article(**kwargs):
            article_index = int(kwargs["article_index"])
            call_order.append(f"open_{article_index}")
            return {
                "target_title": f"article-{article_index}",
                "click_started_at": time.time(),
                "click_result": {"ok": True},
            }

        def close_detail_windows(**kwargs):
            call_order.append(f"cleanup_{kwargs.get('reason', 'unknown')}")
            return {"ok": True, "closed": [{"hwnd": 900}], "skipped": [], "errors": []}

        deps = ArticleCaptureDependencies(
            put_event=lambda event_queue, level, message, **kwargs: event_queue.put({"level": level, "message": message, **kwargs}),
            create_public_article_store=lambda _path: FakeStore(),
            find_wechat_home_window=lambda: FakeHomeWindow(),
            home_article_cursor_cls=FakeCursor,
            open_home_article_for_capture=open_article,
            close_detail_windows=close_detail_windows,
            click_home_article=lambda *_args, **_kwargs: {"ok": True},
            write_probe=lambda *_args, **_kwargs: None,
            drain_capture_events=lambda _queue: 0,
            collect_report=lambda *_args, **_kwargs: {"ready": True},
            resolve_timeout=lambda _config: 1.0,
            is_report_ready=lambda _report: True,
            resolve_failure_reason=lambda _report: "",
            resolve_failure_title=lambda _report, title, _index: title,
            build_ready_message=lambda _report: "ready",
            get_capture_source=lambda _report: "test",
            build_archive=lambda *_args, **_kwargs: {"archive": True},
            build_record=lambda _archive: {
                "account_name": "account-a",
                "article_title": f"saved-{call_order.count('save') + 1}",
                "published_article_time": "2026-06-20 20:00",
                "article_link": f"https://mp.weixin.qq.com/s/test-{call_order.count('save') + 1}",
                "record_type": "article-detail",
                "collect_time": "2026-06-20 20:00:00",
                "collect_status": "saved",
            },
            build_failed_record=build_failed_public_article_record,
        )

        run_article_capture_flow(
            Queue(),
            {
                "account_name": "account-a",
                "enable_home_article_click": True,
                "wechat_detail_window_close_every_articles": 5,
                "request_interval_seconds": 0,
                "run_options": {"recordLimit": 2, "selections": {"articleDetail": True}},
            },
            Queue(),
            deps,
        )

        cleanup_calls = [item for item in call_order if item.startswith("cleanup_")]
        self.assertEqual(cleanup_calls, ["cleanup_start", "cleanup_article_done", "cleanup_article_done", "cleanup_finish"])
        self.assertLess(call_order.index("open_1"), call_order.index("cleanup_article_done"), call_order)
        self.assertLess(call_order.index("cleanup_article_done"), call_order.index("open_2"), call_order)

    def test_flow_reuses_initial_home_window_when_relocation_finds_nothing(self) -> None:
        from src.workers.article_capture_flow import ArticleCaptureDependencies, run_article_capture_flow

        find_calls = {"count": 0}
        cursor_creations = {"count": 0}
        home_window = FakeHomeWindow()

        class FakeCandidate:
            title = "恢复后文章"
            article_index = 1
            rect = (100, 100, 500, 140)
            hwnd = 200

        class FakeCursor:
            def __init__(self, *_args, **kwargs) -> None:
                cursor_creations["count"] += 1
                self.home_window = kwargs.get("home_window")
                self.has_visible_candidates = cursor_creations["count"] > 1
                self.items = [FakeCandidate()] if cursor_creations["count"] > 1 else []

            def next_candidate(self):
                if not self.items:
                    self.has_visible_candidates = False
                    return None
                return self.items.pop(0)

        class FakeStore:
            def has_saved_public_article_title(self, _account_name: str, _title: str) -> bool:
                return False

            def save_public_article(self, _record: dict) -> None:
                pass

        def find_home_window():
            find_calls["count"] += 1
            return home_window if find_calls["count"] == 1 else None

        def open_article(**kwargs):
            self.assertIs(kwargs.get("home_window"), home_window)
            return {"target_title": "恢复后文章", "click_started_at": time.time(), "click_result": {"ok": True}}

        deps = ArticleCaptureDependencies(
            put_event=lambda event_queue, level, message, **kwargs: event_queue.put({"level": level, "message": message, **kwargs}),
            create_public_article_store=lambda _path: FakeStore(),
            find_wechat_home_window=find_home_window,
            home_article_cursor_cls=FakeCursor,
            open_home_article_for_capture=open_article,
            close_detail_windows=lambda **_kwargs: {"ok": True, "closed": [], "skipped": [], "errors": []},
            click_home_article=lambda *_args, **_kwargs: {"ok": True},
            write_probe=lambda *_args, **_kwargs: None,
            drain_capture_events=lambda _queue: 0,
            collect_report=lambda *_args, **_kwargs: {"ready": True},
            resolve_timeout=lambda _config: 1.0,
            is_report_ready=lambda _report: True,
            resolve_failure_reason=lambda _report: "",
            resolve_failure_title=lambda _report, title, _index: title,
            build_ready_message=lambda _report: "ready",
            get_capture_source=lambda _report: "test",
            build_archive=lambda *_args, **_kwargs: {"archive": True},
            build_record=lambda _archive: {
                "account_name": "account-a",
                "article_title": "恢复后文章",
                "published_article_time": "2026-06-21 10:00",
                "article_link": "https://mp.weixin.qq.com/s/recovered-once",
                "record_type": "article-detail",
                "collect_time": "2026-06-21 10:00:00",
                "collect_status": "saved",
            },
            build_failed_record=build_failed_public_article_record,
        )

        run_article_capture_flow(
            Queue(),
            {
                "account_name": "account-a",
                "enable_home_article_click": True,
                "homepage_candidate_wait_timeout_seconds": 1,
                "homepage_candidate_wait_interval_seconds": 0,
                "run_options": {"recordLimit": 1, "selections": {"articleDetail": True}},
            },
            Queue(),
            deps,
        )

        self.assertEqual(find_calls["count"], 2)

    def test_flow_waits_between_articles_when_request_interval_is_configured(self) -> None:
        from src.workers.article_capture_flow import ArticleCaptureDependencies, run_article_capture_flow

        call_order: list[str] = []
        saved_links: list[str] = []

        class FakeCandidate:
            def __init__(self, title: str, article_index: int) -> None:
                self.title = title
                self.article_index = article_index
                self.rect = (100, 100, 500, 140)
                self.hwnd = 200

        class FakeCursor:
            def __init__(self, *_args, **_kwargs) -> None:
                self.items = [FakeCandidate("first", 1), FakeCandidate("second", 2)]

            def next_candidate(self):
                call_order.append("next_candidate")
                if not self.items:
                    return None
                return self.items.pop(0)

            def invalidate(self) -> None:
                pass

        class FakeStore:
            def has_saved_public_article_title(self, _account_name: str, _title: str) -> bool:
                return False

            def save_public_article(self, record: dict) -> None:
                saved_links.append(str(record["article_link"]))
                call_order.append(f"save_{len(saved_links)}")

        def put_event(event_queue, level, message, **kwargs):
            event_queue.put({"level": level, "message": message, **kwargs})

        def open_article(article_index: int, **_kwargs):
            call_order.append(f"open_{article_index}")
            return {"target_title": f"article-{article_index}", "click_started_at": time.time(), "click_result": {"ok": True}}

        def sleep(seconds: float) -> None:
            call_order.append(f"sleep_{seconds:g}")

        deps = ArticleCaptureDependencies(
            put_event=put_event,
            create_public_article_store=lambda _path: FakeStore(),
            find_wechat_home_window=lambda: FakeHomeWindow(),
            home_article_cursor_cls=FakeCursor,
            open_home_article_for_capture=open_article,
            close_detail_windows=lambda **_kwargs: {"ok": True, "closed": [], "skipped": [], "errors": []},
            click_home_article=lambda *_args, **_kwargs: {"ok": True},
            write_probe=lambda *_args, **_kwargs: None,
            drain_capture_events=lambda _queue: 0,
            collect_report=lambda *_args, **_kwargs: {"ready": True},
            resolve_timeout=lambda _config: 1.0,
            is_report_ready=lambda _report: True,
            resolve_failure_reason=lambda _report: "",
            resolve_failure_title=lambda _report, title, _index: title,
            build_ready_message=lambda _report: "ready",
            get_capture_source=lambda _report: "test",
            build_archive=lambda *_args, **_kwargs: {"archive": True},
            build_record=lambda _archive: {
                "account_name": "account-a",
                "article_title": "saved",
                "published_article_time": "2026-06-20 20:00",
                "article_link": f"https://mp.weixin.qq.com/s/{len(saved_links) + 1}",
                "record_type": "article-detail",
                "collect_time": "2026-06-20 20:00:00",
                "collect_status": "saved",
            },
            build_failed_record=build_failed_public_article_record,
            sleep=sleep,
        )

        run_article_capture_flow(
            Queue(),
            {
                "account_name": "account-a",
                "enable_home_article_click": True,
                "request_interval_seconds": 3,
                "run_options": {"recordLimit": 2, "selections": {"articleDetail": True}},
            },
            Queue(),
            deps,
        )

        self.assertEqual(call_order.count("sleep_3"), 1, call_order)
        self.assertLess(call_order.index("save_1"), call_order.index("sleep_3"), call_order)
        self.assertLess(call_order.index("sleep_3"), call_order.index("open_2"), call_order)

    def test_flow_saves_failed_record_when_mitm_wait_times_out(self) -> None:
        from src.workers.article_capture_flow import ArticleCaptureDependencies, run_article_capture_flow

        saved_records: list[dict] = []

        class FakeCandidate:
            title = "超时文章标题"
            article_index = 1
            rect = (100, 100, 500, 140)
            hwnd = 200

        class FakeCursor:
            def __init__(self, *_args, **_kwargs) -> None:
                self.items = [FakeCandidate()]

            def next_candidate(self):
                if not self.items:
                    return None
                return self.items.pop(0)

        class FakeStore:
            def has_saved_public_article_title(self, _account_name: str, _title: str) -> bool:
                return False

            def save_public_article(self, record: dict) -> None:
                saved_records.append(record)

        def put_event(event_queue, level, message, **kwargs):
            event_queue.put({"level": level, "message": message, **kwargs})

        deps = ArticleCaptureDependencies(
            put_event=put_event,
            create_public_article_store=lambda _path: FakeStore(),
            find_wechat_home_window=lambda: FakeHomeWindow(),
            home_article_cursor_cls=FakeCursor,
            open_home_article_for_capture=lambda **_kwargs: {"target_title": "超时文章标题", "click_started_at": time.time()},
            close_detail_windows=lambda **_kwargs: {"ok": True, "closed": [], "skipped": [], "errors": []},
            click_home_article=lambda *_args, **_kwargs: {"ok": True},
            write_probe=lambda *_args, **_kwargs: None,
            drain_capture_events=lambda _queue: 0,
            collect_report=lambda *_args, **_kwargs: {
                "created_at": "2026-06-21 10:00:00",
                "automation_error": "等待 MITM 捕获文章主 HTML 超时：10 秒内未获取到带 key URL",
                "target_article": {"title": "超时文章标题"},
            },
            resolve_timeout=lambda _config: 10.0,
            is_report_ready=lambda _report: False,
            resolve_failure_reason=lambda report: str(report.get("automation_error") or ""),
            resolve_failure_title=lambda _report, title, _index: title,
            build_ready_message=lambda _report: "ready",
            get_capture_source=lambda _report: "",
            build_archive=lambda *_args, **_kwargs: {"archive": True},
            build_record=lambda _archive: {
                "account_name": "account-a",
                "article_title": "should-not-save-success",
                "published_article_time": "2026-06-21 10:00",
                "article_link": "https://mp.weixin.qq.com/s/should-not-save",
                "record_type": "article-detail",
                "collect_time": "2026-06-21 10:00:00",
                "collect_status": "saved",
            },
            build_failed_record=build_failed_public_article_record,
        )

        run_article_capture_flow(
            Queue(),
            {
                "account_name": "测试公众号",
                "enable_home_article_click": True,
                "run_options": {"recordLimit": 1, "selections": {"articleDetail": True}},
            },
            Queue(),
            deps,
        )

        self.assertEqual(len(saved_records), 1)
        self.assertEqual(saved_records[0]["collect_status"], "failed")
        self.assertEqual(saved_records[0]["article_title"], "超时文章标题")
        self.assertEqual(saved_records[0]["article_link"], "")
        self.assertEqual(saved_records[0]["published_article_time"], "")
        self.assertEqual(saved_records[0]["record_type"], "文章详情")
        self.assertGreaterEqual(saved_records[0]["duration_seconds"], 0)

    def test_flow_retries_one_article_before_saving_failure_record(self) -> None:
        from src.workers.article_capture_flow import ArticleCaptureDependencies, run_article_capture_flow

        saved_records: list[dict] = []
        report_calls = {"count": 0}
        open_calls: list[int] = []

        class FakeCandidate:
            title = "重试文章标题"
            article_index = 1
            rect = (100, 100, 500, 140)
            hwnd = 200

        class FakeCursor:
            def __init__(self, *_args, **_kwargs) -> None:
                self.items = [FakeCandidate()]

            def next_candidate(self):
                if not self.items:
                    return None
                return self.items.pop(0)

            def invalidate(self) -> None:
                pass

        class FakeStore:
            def has_saved_public_article_title(self, _account_name: str, _title: str) -> bool:
                return False

            def save_public_article(self, record: dict) -> None:
                saved_records.append(record)

        def open_article(article_index: int, **_kwargs):
            open_calls.append(article_index)
            return {"target_title": "重试文章标题", "click_started_at": time.time(), "click_result": {"ok": True}}

        def collect_report(*_args, **_kwargs):
            report_calls["count"] += 1
            if report_calls["count"] == 1:
                return {
                    "created_at": "2026-06-21 10:00:00",
                    "automation_error": "等待 MITM 捕获文章主 HTML 超时",
                    "target_article": {"title": "重试文章标题"},
                }
            return {"ready": True}

        def put_event(event_queue, level, message, **kwargs):
            event_queue.put({"level": level, "message": message, **kwargs})

        deps = ArticleCaptureDependencies(
            put_event=put_event,
            create_public_article_store=lambda _path: FakeStore(),
            find_wechat_home_window=lambda: FakeHomeWindow(),
            home_article_cursor_cls=FakeCursor,
            open_home_article_for_capture=open_article,
            close_detail_windows=lambda **_kwargs: {"ok": True, "closed": [], "skipped": [], "errors": []},
            click_home_article=lambda *_args, **_kwargs: {"ok": True},
            write_probe=lambda *_args, **_kwargs: None,
            drain_capture_events=lambda _queue: 0,
            collect_report=collect_report,
            resolve_timeout=lambda _config: 1.0,
            is_report_ready=lambda report: bool(report.get("ready")),
            resolve_failure_reason=lambda report: str(report.get("automation_error") or ""),
            resolve_failure_title=lambda _report, title, _index: title,
            build_ready_message=lambda _report: "ready",
            get_capture_source=lambda _report: "test",
            build_archive=lambda *_args, **_kwargs: {"archive": True},
            build_record=lambda _archive: {
                "account_name": "测试公众号",
                "article_title": "重试后成功",
                "published_article_time": "2026-06-21 10:00",
                "article_link": "https://mp.weixin.qq.com/s/retry-success",
                "record_type": "文章详情",
                "collect_time": "2026-06-21 10:00:00",
                "collect_status": "saved",
            },
            build_failed_record=build_failed_public_article_record,
        )

        event_queue = Queue()
        run_article_capture_flow(
            event_queue,
            {
                "account_name": "测试公众号",
                "enable_home_article_click": True,
                "retry_count": 1,
                "run_options": {"recordLimit": 1, "selections": {"articleDetail": True}},
            },
            Queue(),
            deps,
        )

        self.assertEqual(open_calls, [1, 1])
        self.assertEqual(len(saved_records), 1)
        self.assertEqual(saved_records[0]["collect_status"], "saved")
        messages = [item.get("message", "") for item in drain_queue(event_queue)]
        self.assertTrue(any("第 1 次重试" in message for message in messages), messages)

    def test_flow_does_not_retry_when_mitm_never_sees_article_main_request(self) -> None:
        from src.workers.article_capture_flow import ArticleCaptureDependencies, run_article_capture_flow

        saved_records: list[dict] = []
        open_calls: list[int] = []

        class FakeCandidate:
            title = "缓存命中文章"
            article_index = 1
            rect = (100, 100, 500, 140)
            hwnd = 200

        class FakeCursor:
            def __init__(self, *_args, **_kwargs) -> None:
                self.items = [FakeCandidate()]

            def next_candidate(self):
                if not self.items:
                    return None
                return self.items.pop(0)

            def invalidate(self) -> None:
                pass

        class FakeStore:
            def has_saved_public_article_title(self, _account_name: str, _title: str) -> bool:
                return False

            def save_public_article(self, record: dict) -> None:
                saved_records.append(record)

        def open_article(article_index: int, **_kwargs):
            open_calls.append(article_index)
            return {"target_title": "缓存命中文章", "click_started_at": time.time(), "click_result": {"ok": True}}

        deps = ArticleCaptureDependencies(
            put_event=lambda event_queue, level, message, **kwargs: event_queue.put({"level": level, "message": message, **kwargs}),
            create_public_article_store=lambda _path: FakeStore(),
            find_wechat_home_window=lambda: FakeHomeWindow(),
            home_article_cursor_cls=FakeCursor,
            open_home_article_for_capture=open_article,
            close_detail_windows=lambda **_kwargs: {"ok": True, "closed": [], "skipped": [], "errors": []},
            click_home_article=lambda *_args, **_kwargs: {"ok": True},
            write_probe=lambda *_args, **_kwargs: None,
            drain_capture_events=lambda _queue: 0,
            collect_report=lambda *_args, **_kwargs: {
                "created_at": "2026-06-21 10:00:00",
                "automation_error": "等待 MITM 捕获文章主 HTML 超时；MITM 未看到文章主页面请求，可能命中本地缓存",
                "target_article": {"title": "缓存命中文章"},
            },
            resolve_timeout=lambda _config: 1.0,
            is_report_ready=lambda _report: False,
            resolve_failure_reason=lambda report: str(report.get("automation_error") or ""),
            resolve_failure_title=lambda _report, title, _index: title,
            build_ready_message=lambda _report: "ready",
            get_capture_source=lambda _report: "test",
            build_archive=lambda *_args, **_kwargs: {"archive": True},
            build_record=lambda _archive: {
                "account_name": "测试公众号",
                "article_title": "不应成功",
                "published_article_time": "2026-06-21 10:00",
                "article_link": "https://mp.weixin.qq.com/s/not-saved",
                "record_type": "文章详情",
                "collect_time": "2026-06-21 10:00:00",
                "collect_status": "saved",
            },
            build_failed_record=build_failed_public_article_record,
        )

        event_queue = Queue()
        run_article_capture_flow(
            event_queue,
            {
                "account_name": "测试公众号",
                "enable_home_article_click": True,
                "retry_count": 3,
                "run_options": {"recordLimit": 1, "selections": {"articleDetail": True}},
            },
            Queue(),
            deps,
        )

        self.assertEqual(open_calls, [1])
        self.assertEqual(len(saved_records), 1)
        self.assertEqual(saved_records[0]["collect_status"], "failed")
        messages = [item.get("message", "") for item in drain_queue(event_queue)]
        self.assertFalse(any("准备第" in message and "重试" in message for message in messages), messages)

    def test_flow_skips_non_retriable_failed_title_in_same_run_and_fills_saved_target(self) -> None:
        from src.workers.article_capture_flow import ArticleCaptureDependencies, run_article_capture_flow

        saved_records: list[dict] = []
        failed_records: list[dict] = []
        open_titles: list[str] = []

        class FakeCandidate:
            def __init__(self, title: str, article_index: int) -> None:
                self.title = title
                self.article_index = article_index
                self.rect = (100, 100 + article_index * 50, 500, 140 + article_index * 50)
                self.hwnd = 200

        class FakeCursor:
            def __init__(self, *_args, **_kwargs) -> None:
                self.items = [
                    FakeCandidate("卡住文章", 1),
                    FakeCandidate("正常文章A", 2),
                    FakeCandidate("正常文章B", 3),
                ]
                self.position = 0
                self.last_stop_reason = ""

            @property
            def visible_candidates(self):
                return list(self.items)

            @property
            def has_visible_candidates(self):
                return self.position < len(self.items)

            def next_candidate(self):
                if self.position >= len(self.items):
                    return None
                candidate = self.items[self.position]
                self.position += 1
                return candidate

            def refresh_visible_candidates(self) -> bool:
                return self.has_visible_candidates

            def skip_visible_candidates(self, titles=None) -> None:
                title_set = {str(title) for title in titles or []}
                while self.position < len(self.items) and self.items[self.position].title in title_set:
                    self.position += 1

            def invalidate(self) -> None:
                pass

        class FakeStore:
            def has_saved_public_article_title(self, _account_name: str, _title: str) -> bool:
                return str(_title) in {str(record.get("article_title")) for record in saved_records}

            def has_recent_failed_public_article_title(self, _account_name: str, _title: str, **_kwargs) -> bool:
                return False

            def save_public_article(self, record: dict) -> None:
                if record.get("collect_status") == "failed":
                    failed_records.append(record)
                else:
                    saved_records.append(record)

        def open_article(**kwargs):
            candidate = kwargs.get("candidate")
            title = str(getattr(candidate, "title", ""))
            open_titles.append(title)
            return {"target_title": title, "click_started_at": time.time(), "click_result": {"ok": True}}

        def collect_report(_queue, _config, *, target_title: str, **_kwargs):
            if target_title == "卡住文章":
                return {
                    "ready": False,
                    "target_article": {"title": target_title},
                    "storage": {"title": target_title, "account_name": "account-a"},
                    "conclusion": "等待 MITM 捕获文章主 HTML 超时；MITM 未看到文章主页面请求，微信内置浏览器可能复用了缓存",
                }
            return {
                "ready": True,
                "target_article": {"title": target_title},
                "storage": {"title": target_title, "account_name": "account-a"},
            }

        def build_record(_archive):
            title = open_titles[-1]
            return {
                "account_name": "account-a",
                "article_title": title,
                "published_article_time": "2026-06-30 12:00",
                "article_link": f"https://mp.weixin.qq.com/s/{title}",
                "record_type": "文章详情",
                "collect_time": "2026-06-30 12:00:00",
                "collect_status": "saved",
            }

        event_queue = Queue()
        deps = ArticleCaptureDependencies(
            put_event=lambda queue, level, message, **kwargs: queue.put({"level": level, "message": message, **kwargs}),
            create_public_article_store=lambda _path: FakeStore(),
            find_wechat_home_window=lambda: FakeHomeWindow(),
            home_article_cursor_cls=FakeCursor,
            open_home_article_for_capture=open_article,
            close_detail_windows=lambda **_kwargs: {"ok": True, "closed": [], "skipped": [], "errors": []},
            click_home_article=lambda *_args, **_kwargs: {"ok": True},
            write_probe=lambda *_args, **_kwargs: None,
            drain_capture_events=lambda _queue: 0,
            collect_report=collect_report,
            resolve_timeout=lambda _config: 1.0,
            is_report_ready=lambda report: bool(report.get("ready")),
            resolve_failure_reason=lambda report: str(report.get("conclusion") or ""),
            resolve_failure_title=lambda report, title, _index: str(report.get("target_article", {}).get("title") or title),
            build_ready_message=lambda _report: "ready",
            get_capture_source=lambda _report: "test",
            build_archive=lambda *_args, **_kwargs: {"archive": True},
            build_record=build_record,
            build_failed_record=build_failed_public_article_record,
        )

        run_article_capture_flow(
            event_queue,
            {
                "account_name": "account-a",
                "enable_home_article_click": True,
                "request_interval_seconds": 0,
                "run_options": {"recordLimit": 2, "selections": {"articleDetail": True}},
            },
            Queue(),
            deps,
        )

        self.assertEqual(open_titles, ["卡住文章", "正常文章A", "正常文章B"])
        self.assertEqual([record["article_title"] for record in saved_records], ["正常文章A", "正常文章B"])
        self.assertEqual([record["article_title"] for record in failed_records], ["卡住文章"])
        messages = [item.get("message", "") for item in drain_queue(event_queue)]
        self.assertTrue(any("加入本轮跳过列表" in message for message in messages), messages)

    def test_flow_stops_when_repeated_skips_make_no_progress(self) -> None:
        from src.workers.article_capture_flow import ArticleCaptureDependencies, run_article_capture_flow

        open_titles: list[str] = []
        emitted_events: list[dict] = []

        class FakeCandidate:
            title = "重复旧文章"
            article_index = 1
            rect = (100, 100, 500, 140)
            hwnd = 200

        class FakeCursor:
            def __init__(self, *_args, **_kwargs) -> None:
                self.last_stop_reason = ""

            @property
            def visible_candidates(self):
                return [FakeCandidate()]

            @property
            def has_visible_candidates(self):
                return True

            def next_candidate(self):
                return FakeCandidate()

            def refresh_visible_candidates(self) -> bool:
                return True

            def skip_visible_candidates(self, titles=None) -> None:
                pass

            def invalidate(self) -> None:
                pass

        class FakeStore:
            def has_saved_public_article_title(self, _account_name: str, _title: str) -> bool:
                return True

            def has_recent_failed_public_article_title(self, _account_name: str, _title: str, **_kwargs) -> bool:
                return False

            def save_public_article(self, _record: dict) -> None:
                raise AssertionError("repeated skip scenario should not save records")

        def put_event(event_queue, level, message, **kwargs):
            payload = {"level": level, "message": message, **kwargs}
            emitted_events.append(payload)
            event_queue.put(payload)

        deps = ArticleCaptureDependencies(
            put_event=put_event,
            create_public_article_store=lambda _path: FakeStore(),
            find_wechat_home_window=lambda: FakeHomeWindow(),
            home_article_cursor_cls=FakeCursor,
            open_home_article_for_capture=lambda **kwargs: open_titles.append(str(kwargs.get("article_index"))) or {},
            close_detail_windows=lambda **_kwargs: {"ok": True, "closed": [], "skipped": [], "errors": []},
            click_home_article=lambda *_args, **_kwargs: {"ok": True},
            write_probe=lambda *_args, **_kwargs: None,
            drain_capture_events=lambda _queue: 0,
            collect_report=lambda *_args, **_kwargs: {"ready": True},
            resolve_timeout=lambda _config: 1.0,
            is_report_ready=lambda _report: True,
            resolve_failure_reason=lambda _report: "",
            resolve_failure_title=lambda _report, title, _index: title,
            build_ready_message=lambda _report: "ready",
            get_capture_source=lambda _report: "test",
            build_archive=lambda *_args, **_kwargs: {"archive": True},
            build_record=lambda _archive: {},
            build_failed_record=build_failed_public_article_record,
        )

        event_queue = Queue()
        run_article_capture_flow(
            event_queue,
            {
                "account_name": "account-a",
                "enable_home_article_click": True,
                "homepage_max_cursor_iterations": 5,
                "homepage_max_no_progress_iterations": 3,
                "run_options": {"recordLimit": 2, "selections": {"articleDetail": True}},
            },
            Queue(),
            deps,
        )

        self.assertEqual(open_titles, [])
        messages = [item.get("message", "") for item in drain_queue(event_queue)]
        self.assertTrue(any("连续 3 次未产生新的保存结果" in message for message in messages), messages)
        self.assertLessEqual(len(emitted_events), 8)

    def test_flow_uses_confirmed_account_for_later_failed_record_when_home_account_unreadable(self) -> None:
        from src.workers.article_capture_flow import ArticleCaptureDependencies, run_article_capture_flow

        saved_records: list[dict] = []
        report_calls = {"count": 0}

        class FakeCandidate:
            def __init__(self, title: str, article_index: int) -> None:
                self.title = title
                self.article_index = article_index
                self.rect = (100, 100, 500, 140)
                self.hwnd = 200

        class FakeCursor:
            def __init__(self, *_args, **_kwargs) -> None:
                self.items = [FakeCandidate("成功文章", 1), FakeCandidate("超时文章标题", 2)]

            def next_candidate(self):
                if not self.items:
                    return None
                return self.items.pop(0)

            def invalidate(self) -> None:
                pass

        class FakeStore:
            def has_saved_public_article_title(self, _account_name: str, _title: str) -> bool:
                return False

            def save_public_article(self, record: dict) -> None:
                saved_records.append(record)

        def put_event(event_queue, level, message, **kwargs):
            event_queue.put({"level": level, "message": message, **kwargs})

        def collect_report(*_args, **_kwargs):
            report_calls["count"] += 1
            if report_calls["count"] == 1:
                return {"ready": True}
            return {
                "created_at": "2026-06-21 10:00:00",
                "automation_error": "等待 MITM 捕获文章主 HTML 超时",
                "target_article": {"title": "超时文章标题"},
            }

        deps = ArticleCaptureDependencies(
            put_event=put_event,
            create_public_article_store=lambda _path: FakeStore(),
            find_wechat_home_window=lambda: FakeHomeWindow(),
            home_article_cursor_cls=FakeCursor,
            open_home_article_for_capture=lambda article_index, **_kwargs: {
                "target_title": "成功文章" if int(article_index) == 1 else "超时文章标题",
                "click_started_at": time.time(),
                "click_result": {"ok": True},
            },
            close_detail_windows=lambda **_kwargs: {"ok": True, "closed": [], "skipped": [], "errors": []},
            click_home_article=lambda *_args, **_kwargs: {"ok": True},
            write_probe=lambda *_args, **_kwargs: None,
            drain_capture_events=lambda _queue: 0,
            collect_report=collect_report,
            resolve_timeout=lambda _config: 1.0,
            is_report_ready=lambda report: bool(report.get("ready")),
            resolve_failure_reason=lambda report: str(report.get("automation_error") or ""),
            resolve_failure_title=lambda _report, title, _index: title,
            build_ready_message=lambda _report: "ready",
            get_capture_source=lambda _report: "test",
            build_archive=lambda *_args, **_kwargs: {"archive": True},
            build_record=lambda _archive: {
                "account_name": "新华社",
                "article_title": "成功文章",
                "published_article_time": "2026-06-21 10:00",
                "article_link": "https://mp.weixin.qq.com/s/success",
                "record_type": "文章详情",
                "collect_time": "2026-06-21 10:00:00",
                "collect_status": "saved",
            },
            build_failed_record=build_failed_public_article_record,
        )

        run_article_capture_flow(
            Queue(),
            {
                "enable_home_article_click": True,
                "run_options": {"recordLimit": 2, "selections": {"articleDetail": True}},
            },
            Queue(),
            deps,
        )

        self.assertEqual(len(saved_records), 2)
        self.assertEqual(saved_records[1]["collect_status"], "failed")
        self.assertEqual(saved_records[1]["account_name"], "新华社")
        self.assertEqual(saved_records[1]["article_title"], "超时文章标题")
        self.assertEqual(saved_records[1]["article_link"], "")

    def test_flow_flushes_early_failed_record_after_account_is_confirmed_later(self) -> None:
        from src.workers.article_capture_flow import ArticleCaptureDependencies, run_article_capture_flow

        saved_records: list[dict] = []
        report_calls = {"count": 0}

        class FakeCandidate:
            def __init__(self, title: str, article_index: int) -> None:
                self.title = title
                self.article_index = article_index
                self.rect = (100, 100, 500, 140)
                self.hwnd = 200

        class FakeCursor:
            def __init__(self, *_args, **_kwargs) -> None:
                self.items = [FakeCandidate("先失败文章", 1), FakeCandidate("后成功文章", 2)]

            def next_candidate(self):
                if not self.items:
                    return None
                return self.items.pop(0)

            def invalidate(self) -> None:
                pass

        class FakeStore:
            def has_saved_public_article_title(self, _account_name: str, _title: str) -> bool:
                return False

            def save_public_article(self, record: dict) -> None:
                saved_records.append(record)

        def put_event(event_queue, level, message, **kwargs):
            event_queue.put({"level": level, "message": message, **kwargs})

        def collect_report(*_args, **_kwargs):
            report_calls["count"] += 1
            if report_calls["count"] == 1:
                return {
                    "created_at": "2026-06-21 10:00:00",
                    "automation_error": "等待 MITM 捕获文章主 HTML 超时",
                    "target_article": {"title": "先失败文章"},
                }
            return {"ready": True}

        deps = ArticleCaptureDependencies(
            put_event=put_event,
            create_public_article_store=lambda _path: FakeStore(),
            find_wechat_home_window=lambda: FakeHomeWindow(),
            home_article_cursor_cls=FakeCursor,
            open_home_article_for_capture=lambda article_index, **_kwargs: {
                "target_title": "先失败文章" if int(article_index) == 1 else "后成功文章",
                "click_started_at": time.time(),
                "click_result": {"ok": True},
            },
            close_detail_windows=lambda **_kwargs: {"ok": True, "closed": [], "skipped": [], "errors": []},
            click_home_article=lambda *_args, **_kwargs: {"ok": True},
            write_probe=lambda *_args, **_kwargs: None,
            drain_capture_events=lambda _queue: 0,
            collect_report=collect_report,
            resolve_timeout=lambda _config: 1.0,
            is_report_ready=lambda report: bool(report.get("ready")),
            resolve_failure_reason=lambda report: str(report.get("automation_error") or ""),
            resolve_failure_title=lambda _report, title, _index: title,
            build_ready_message=lambda _report: "ready",
            get_capture_source=lambda _report: "test",
            build_archive=lambda *_args, **_kwargs: {"archive": True},
            build_record=lambda _archive: {
                "account_name": "新华社",
                "article_title": "后成功文章",
                "published_article_time": "2026-06-21 10:00",
                "article_link": "https://mp.weixin.qq.com/s/success-after-failure",
                "record_type": "文章详情",
                "collect_time": "2026-06-21 10:00:03",
                "collect_status": "saved",
            },
            build_failed_record=build_failed_public_article_record,
        )

        run_article_capture_flow(
            Queue(),
            {
                "enable_home_article_click": True,
                "run_options": {"recordLimit": 2, "selections": {"articleDetail": True}},
            },
            Queue(),
            deps,
        )

        self.assertEqual(len(saved_records), 2)
        self.assertEqual(saved_records[0]["collect_status"], "saved")
        self.assertEqual(saved_records[1]["collect_status"], "failed")
        self.assertEqual(saved_records[1]["account_name"], "新华社")
        self.assertEqual(saved_records[1]["article_title"], "先失败文章")
        self.assertEqual(saved_records[1]["article_link"], "")

    def test_flow_fast_fails_when_home_click_has_no_article_target(self) -> None:
        from src.workers.article_capture_flow import ArticleCaptureDependencies, run_article_capture_flow

        saved_records: list[dict] = []
        collect_report_calls = 0

        class FakeCandidate:
            title = ""
            article_index = 1
            rect = (100, 100, 500, 140)
            hwnd = 200

        class FakeCursor:
            def __init__(self, *_args, **_kwargs) -> None:
                self.items = [FakeCandidate()]

            def next_candidate(self):
                if not self.items:
                    return None
                return self.items.pop(0)

        class FakeStore:
            def has_saved_public_article_title(self, _account_name: str, _title: str) -> bool:
                return False

            def save_public_article(self, record: dict) -> None:
                saved_records.append(record)

        def put_event(event_queue, level, message, **kwargs):
            event_queue.put({"level": level, "message": message, **kwargs})

        def collect_report(*_args, **_kwargs):
            nonlocal collect_report_calls
            collect_report_calls += 1
            return {"automation_error": "should-not-wait-mitm"}

        deps = ArticleCaptureDependencies(
            put_event=put_event,
            create_public_article_store=lambda _path: FakeStore(),
            find_wechat_home_window=lambda: FakeHomeWindow(),
            home_article_cursor_cls=FakeCursor,
            open_home_article_for_capture=lambda **_kwargs: {
                "target_title": "",
                "click_started_at": time.time(),
                "click_result": {
                    "ok": False,
                    "reason": "article_click_target_not_found",
                    "visible_targets": [],
                },
            },
            close_detail_windows=lambda **_kwargs: {"ok": True, "closed": [], "skipped": [], "errors": []},
            click_home_article=lambda *_args, **_kwargs: {"ok": False},
            write_probe=lambda *_args, **_kwargs: None,
            drain_capture_events=lambda _queue: 0,
            collect_report=collect_report,
            resolve_timeout=lambda _config: 10.0,
            is_report_ready=lambda _report: False,
            resolve_failure_reason=lambda report: str(report.get("automation_error") or ""),
            resolve_failure_title=lambda _report, title, _index: title or "未识别标题",
            build_ready_message=lambda _report: "ready",
            get_capture_source=lambda _report: "",
            build_archive=lambda *_args, **_kwargs: {"archive": True},
            build_record=lambda _archive: {
                "account_name": "account-a",
                "article_title": "should-not-save-success",
                "published_article_time": "2026-06-21 10:00",
                "article_link": "https://mp.weixin.qq.com/s/should-not-save",
                "record_type": "article-detail",
                "collect_time": "2026-06-21 10:00:00",
                "collect_status": "saved",
            },
            build_failed_record=build_failed_public_article_record,
        )

        event_queue = Queue()
        run_article_capture_flow(
            event_queue,
            {
                "account_name": "测试公众号",
                "enable_home_article_click": True,
                "run_options": {"recordLimit": 1, "selections": {"articleDetail": True}},
            },
            Queue(),
            deps,
        )

        self.assertEqual(collect_report_calls, 0)
        self.assertEqual(saved_records, [])
        messages = [item.get("message", "") for item in drain_queue(event_queue)]
        self.assertTrue(any("点击阶段未找到可打开的主页文章" in message for message in messages), messages)

    def test_flow_waits_for_home_candidates_instead_of_legacy_fallback_when_temporarily_unreadable(self) -> None:
        from src.workers.article_capture_flow import ArticleCaptureDependencies, run_article_capture_flow

        saved_records: list[dict] = []
        open_calls: list[int] = []
        cursor_creations = {"count": 0}

        class FakeCandidate:
            title = "恢复后文章"
            article_index = 1
            rect = (100, 100, 500, 140)
            hwnd = 200

        class FakeCursor:
            def __init__(self, *_args, **_kwargs) -> None:
                cursor_creations["count"] += 1
                self.has_visible_candidates = cursor_creations["count"] > 1
                self.items = [FakeCandidate()] if cursor_creations["count"] > 1 else []

            def next_candidate(self):
                if not self.items:
                    self.has_visible_candidates = False
                    return None
                return self.items.pop(0)

        class FakeStore:
            def has_saved_public_article_title(self, _account_name: str, _title: str) -> bool:
                return False

            def save_public_article(self, record: dict) -> None:
                saved_records.append(record)

        def put_event(event_queue, level, message, **kwargs):
            event_queue.put({"level": level, "message": message, **kwargs})

        def open_article(**kwargs):
            open_calls.append(int(kwargs["article_index"]))
            return {"target_title": "恢复后文章", "click_started_at": time.time(), "click_result": {"ok": True}}

        deps = ArticleCaptureDependencies(
            put_event=put_event,
            create_public_article_store=lambda _path: FakeStore(),
            find_wechat_home_window=lambda: FakeHomeWindow(),
            home_article_cursor_cls=FakeCursor,
            open_home_article_for_capture=open_article,
            close_detail_windows=lambda **_kwargs: {"ok": True, "closed": [], "skipped": [], "errors": []},
            click_home_article=lambda *_args, **_kwargs: {"ok": True},
            write_probe=lambda *_args, **_kwargs: None,
            drain_capture_events=lambda _queue: 0,
            collect_report=lambda *_args, **_kwargs: {"ready": True},
            resolve_timeout=lambda _config: 1.0,
            is_report_ready=lambda _report: True,
            resolve_failure_reason=lambda _report: "",
            resolve_failure_title=lambda _report, title, _index: title,
            build_ready_message=lambda _report: "ready",
            get_capture_source=lambda _report: "test",
            build_archive=lambda *_args, **_kwargs: {"archive": True},
            build_record=lambda _archive: {
                "account_name": "account-a",
                "article_title": "恢复后文章",
                "published_article_time": "2026-06-21 10:00",
                "article_link": "https://mp.weixin.qq.com/s/recovered",
                "record_type": "article-detail",
                "collect_time": "2026-06-21 10:00:00",
                "collect_status": "saved",
            },
            build_failed_record=build_failed_public_article_record,
        )

        event_queue = Queue()
        run_article_capture_flow(
            event_queue,
            {
                "account_name": "测试公众号",
                "enable_home_article_click": True,
                "homepage_candidate_wait_timeout_seconds": 1,
                "homepage_candidate_wait_interval_seconds": 0,
                "run_options": {"recordLimit": 1, "selections": {"articleDetail": True}},
            },
            Queue(),
            deps,
        )

        self.assertEqual(open_calls, [1])
        self.assertEqual(len(saved_records), 1)
        messages = [item.get("message", "") for item in drain_queue(event_queue)]
        self.assertTrue(any("重新定位并激活微信主页" in message for message in messages), messages)
        self.assertFalse(any("回退为按序号点击采集" in message for message in messages), messages)

    def test_flow_stops_without_failed_records_when_home_candidates_remain_unreadable(self) -> None:
        from src.workers.article_capture_flow import ArticleCaptureDependencies, run_article_capture_flow

        saved_records: list[dict] = []
        open_calls: list[int] = []

        class FakeCursor:
            has_visible_candidates = False

            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def next_candidate(self):
                return None

        class FakeStore:
            def has_saved_public_article_title(self, _account_name: str, _title: str) -> bool:
                return False

            def save_public_article(self, record: dict) -> None:
                saved_records.append(record)

        def put_event(event_queue, level, message, **kwargs):
            event_queue.put({"level": level, "message": message, **kwargs})

        deps = ArticleCaptureDependencies(
            put_event=put_event,
            create_public_article_store=lambda _path: FakeStore(),
            find_wechat_home_window=lambda: FakeHomeWindow(),
            home_article_cursor_cls=FakeCursor,
            open_home_article_for_capture=lambda **kwargs: open_calls.append(int(kwargs["article_index"])) or {
                "target_title": "",
                "click_started_at": time.time(),
                "click_result": {"ok": False, "reason": "article_click_target_not_found"},
            },
            close_detail_windows=lambda **_kwargs: {"ok": True, "closed": [], "skipped": [], "errors": []},
            click_home_article=lambda *_args, **_kwargs: {"ok": False},
            write_probe=lambda *_args, **_kwargs: None,
            drain_capture_events=lambda _queue: 0,
            collect_report=lambda *_args, **_kwargs: {"automation_error": "should-not-wait-mitm"},
            resolve_timeout=lambda _config: 1.0,
            is_report_ready=lambda _report: False,
            resolve_failure_reason=lambda report: str(report.get("automation_error") or ""),
            resolve_failure_title=lambda _report, title, _index: title or "未识别标题",
            build_ready_message=lambda _report: "ready",
            get_capture_source=lambda _report: "",
            build_archive=lambda *_args, **_kwargs: {"archive": True},
            build_record=lambda _archive: {
                "account_name": "account-a",
                "article_title": "should-not-save-success",
                "published_article_time": "2026-06-21 10:00",
                "article_link": "https://mp.weixin.qq.com/s/should-not-save",
                "record_type": "article-detail",
                "collect_time": "2026-06-21 10:00:00",
                "collect_status": "saved",
            },
            build_failed_record=build_failed_public_article_record,
        )

        event_queue = Queue()
        run_article_capture_flow(
            event_queue,
            {
                "account_name": "测试公众号",
                "enable_home_article_click": True,
                "homepage_candidate_wait_timeout_seconds": 0,
                "homepage_candidate_wait_interval_seconds": 0,
                "run_options": {"recordLimit": 20, "selections": {"articleDetail": True}},
            },
            Queue(),
            deps,
        )

        self.assertEqual(open_calls, [])
        self.assertEqual(saved_records, [])
        messages = [item.get("message", "") for item in drain_queue(event_queue)]
        self.assertTrue(any("主页窗口当前不可读" in message for message in messages), messages)

    def test_flow_reselects_current_visible_candidate_before_click_when_home_content_changes(self) -> None:
        from src.workers.article_capture_flow import ArticleCaptureDependencies, run_article_capture_flow

        saved_records: list[dict] = []
        open_calls: list[tuple[int, str]] = []

        class FakeCandidate:
            def __init__(self, title: str, article_index: int, rect=(100, 100, 500, 140)) -> None:
                self.title = title
                self.article_index = article_index
                self.rect = rect
                self.hwnd = 200

        class FakeCursor:
            def __init__(self, *_args, **_kwargs) -> None:
                self.items = [FakeCandidate("文章B", 1)]

            def next_candidate(self):
                if not self.items:
                    return None
                return self.items.pop(0)

            def refresh_visible_candidates(self) -> bool:
                self.items = [FakeCandidate("文章X", 1)]
                return bool(self.items)

            @property
            def visible_candidates(self):
                return list(self.items)

            def invalidate(self) -> None:
                self.items = []

        class FakeStore:
            def has_saved_public_article_title(self, _account_name: str, _title: str) -> bool:
                return False

            def save_public_article(self, record: dict) -> None:
                saved_records.append(record)

        def put_event(event_queue, level, message, **kwargs):
            event_queue.put({"level": level, "message": message, **kwargs})

        def open_article(**kwargs):
            candidate = kwargs.get("candidate")
            open_calls.append((int(kwargs["article_index"]), str(getattr(candidate, "title", ""))))
            return {
                "target_title": str(getattr(candidate, "title", "")),
                "click_started_at": time.time(),
                "click_result": {"ok": True},
            }

        deps = ArticleCaptureDependencies(
            put_event=put_event,
            create_public_article_store=lambda _path: FakeStore(),
            find_wechat_home_window=lambda: FakeHomeWindow(),
            home_article_cursor_cls=FakeCursor,
            open_home_article_for_capture=open_article,
            close_detail_windows=lambda **_kwargs: {"ok": True, "closed": [], "skipped": [], "errors": []},
            click_home_article=lambda *_args, **_kwargs: {"ok": True},
            write_probe=lambda *_args, **_kwargs: None,
            drain_capture_events=lambda _queue: 0,
            collect_report=lambda *_args, **_kwargs: {"ready": True},
            resolve_timeout=lambda _config: 1.0,
            is_report_ready=lambda _report: True,
            resolve_failure_reason=lambda _report: "",
            resolve_failure_title=lambda _report, title, _index: title,
            build_ready_message=lambda _report: "ready",
            get_capture_source=lambda _report: "test",
            build_archive=lambda *_args, **_kwargs: {"archive": True},
            build_record=lambda _archive: {
                "account_name": "account-a",
                "article_title": open_calls[-1][1],
                "published_article_time": "2026-06-21 10:00",
                "article_link": f"https://mp.weixin.qq.com/s/{open_calls[-1][1]}",
                "record_type": "article-detail",
                "collect_time": "2026-06-21 10:00:00",
                "collect_status": "saved",
            },
            build_failed_record=build_failed_public_article_record,
        )

        event_queue = Queue()
        run_article_capture_flow(
            event_queue,
            {
                "account_name": "account-a",
                "enable_home_article_click": True,
                "run_options": {"recordLimit": 1, "selections": {"articleDetail": True}},
            },
            Queue(),
            deps,
        )

        self.assertEqual(open_calls, [(1, "文章X")])
        self.assertEqual(saved_records[0]["article_title"], "文章X")
        messages = [item.get("message", "") for item in drain_queue(event_queue)]
        self.assertTrue(any("点击前主页候选已变化" in message for message in messages), messages)

    def test_flow_ignores_new_visible_candidate_without_clickable_rect_before_click(self) -> None:
        from src.workers.article_capture_flow import ArticleCaptureDependencies, run_article_capture_flow

        open_calls: list[tuple[int, str]] = []

        class FakeCandidate:
            def __init__(self, title: str, article_index: int, rect) -> None:
                self.title = title
                self.article_index = article_index
                self.rect = rect
                self.hwnd = 200

        class FakeCursor:
            def __init__(self, *_args, **_kwargs) -> None:
                self.items = [FakeCandidate("文章B", 1, (100, 100, 500, 140))]

            def next_candidate(self):
                if not self.items:
                    return None
                return self.items.pop(0)

            def refresh_visible_candidates(self) -> bool:
                self.items = [
                    FakeCandidate("文章X", 1, (0, 0, 0, 0)),
                    FakeCandidate("文章Y", 2, (100, 160, 500, 200)),
                ]
                return bool(self.items)

            @property
            def visible_candidates(self):
                return list(self.items)

            def invalidate(self) -> None:
                self.items = []

        class FakeStore:
            def has_saved_public_article_title(self, _account_name: str, _title: str) -> bool:
                return False

            def save_public_article(self, _record: dict) -> None:
                pass

        def open_article(**kwargs):
            candidate = kwargs.get("candidate")
            open_calls.append((int(kwargs["article_index"]), str(getattr(candidate, "title", ""))))
            return {
                "target_title": str(getattr(candidate, "title", "")),
                "click_started_at": time.time(),
                "click_result": {"ok": True},
            }

        deps = ArticleCaptureDependencies(
            put_event=lambda event_queue, level, message, **kwargs: event_queue.put({"level": level, "message": message, **kwargs}),
            create_public_article_store=lambda _path: FakeStore(),
            find_wechat_home_window=lambda: FakeHomeWindow(),
            home_article_cursor_cls=FakeCursor,
            open_home_article_for_capture=open_article,
            close_detail_windows=lambda **_kwargs: {"ok": True, "closed": [], "skipped": [], "errors": []},
            click_home_article=lambda *_args, **_kwargs: {"ok": True},
            write_probe=lambda *_args, **_kwargs: None,
            drain_capture_events=lambda _queue: 0,
            collect_report=lambda *_args, **_kwargs: {"ready": True},
            resolve_timeout=lambda _config: 1.0,
            is_report_ready=lambda _report: True,
            resolve_failure_reason=lambda _report: "",
            resolve_failure_title=lambda _report, title, _index: title,
            build_ready_message=lambda _report: "ready",
            get_capture_source=lambda _report: "test",
            build_archive=lambda *_args, **_kwargs: {"archive": True},
            build_record=lambda _archive: {
                "account_name": "account-a",
                "article_title": open_calls[-1][1],
                "published_article_time": "2026-06-21 10:00",
                "article_link": f"https://mp.weixin.qq.com/s/{open_calls[-1][1]}",
                "record_type": "article-detail",
                "collect_time": "2026-06-21 10:00:00",
                "collect_status": "saved",
            },
            build_failed_record=build_failed_public_article_record,
        )

        run_article_capture_flow(
            Queue(),
            {
                "account_name": "account-a",
                "enable_home_article_click": True,
                "run_options": {"recordLimit": 1, "selections": {"articleDetail": True}},
            },
            Queue(),
            deps,
        )

        self.assertEqual(open_calls, [(2, "文章Y")])

    def test_flow_scrolls_to_next_screen_when_current_visible_candidates_are_saved(self) -> None:
        from src.workers.article_capture_flow import ArticleCaptureDependencies, run_article_capture_flow

        saved_records: list[dict] = []
        open_calls: list[tuple[int, str]] = []

        class FakeCandidate:
            def __init__(self, title: str, article_index: int, rect) -> None:
                self.title = title
                self.article_index = article_index
                self.rect = rect
                self.hwnd = 200

        class FakeCursor:
            def __init__(self, *_args, **_kwargs) -> None:
                self.pages = [
                    [
                        FakeCandidate("已保存A", 1, (100, 100, 500, 140)),
                        FakeCandidate("已保存B", 2, (100, 160, 500, 200)),
                    ],
                    [FakeCandidate("未保存C", 1, (100, 100, 500, 140))],
                ]
                self.page_index = 0
                self.position = 0
                self.last_stop_reason = ""
                self.skip_calls: list[str] = []

            @property
            def visible_candidates(self):
                return list(self.pages[self.page_index])

            @property
            def has_visible_candidates(self):
                return bool(self.visible_candidates)

            def next_candidate(self):
                page = self.pages[self.page_index]
                if self.position < len(page):
                    candidate = page[self.position]
                    self.position += 1
                    return candidate
                if self.page_index + 1 >= len(self.pages):
                    return None
                self.page_index += 1
                self.position = 0
                return self.next_candidate()

            def refresh_visible_candidates(self) -> bool:
                return bool(self.pages[self.page_index])

            def skip_visible_candidates(self, titles=None) -> None:
                self.skip_calls.extend(list(titles or []))
                self.position = len(self.pages[self.page_index])

            def invalidate(self) -> None:
                self.position = 0

        cursor_holder: dict[str, FakeCursor] = {}

        def make_cursor(*_args, **_kwargs):
            cursor = FakeCursor()
            cursor_holder["cursor"] = cursor
            return cursor

        class FakeStore:
            def has_saved_public_article_title(self, _account_name: str, title: str) -> bool:
                return str(title) in {"已保存A", "已保存B"}

            def save_public_article(self, record: dict) -> None:
                saved_records.append(record)

        def open_article(**kwargs):
            candidate = kwargs.get("candidate")
            open_calls.append((int(kwargs["article_index"]), str(getattr(candidate, "title", ""))))
            return {
                "target_title": str(getattr(candidate, "title", "")),
                "click_started_at": time.time(),
                "click_result": {"ok": True},
            }

        deps = ArticleCaptureDependencies(
            put_event=lambda event_queue, level, message, **kwargs: event_queue.put({"level": level, "message": message, **kwargs}),
            create_public_article_store=lambda _path: FakeStore(),
            find_wechat_home_window=lambda: FakeHomeWindow(),
            home_article_cursor_cls=make_cursor,
            open_home_article_for_capture=open_article,
            close_detail_windows=lambda **_kwargs: {"ok": True, "closed": [], "skipped": [], "errors": []},
            click_home_article=lambda *_args, **_kwargs: {"ok": True},
            write_probe=lambda *_args, **_kwargs: None,
            drain_capture_events=lambda _queue: 0,
            collect_report=lambda *_args, **_kwargs: {"ready": True},
            resolve_timeout=lambda _config: 1.0,
            is_report_ready=lambda _report: True,
            resolve_failure_reason=lambda _report: "",
            resolve_failure_title=lambda _report, title, _index: title,
            build_ready_message=lambda _report: "ready",
            get_capture_source=lambda _report: "test",
            build_archive=lambda *_args, **_kwargs: {"archive": True},
            build_record=lambda _archive: {
                "account_name": "account-a",
                "article_title": open_calls[-1][1],
                "published_article_time": "2026-06-21 10:00",
                "article_link": f"https://mp.weixin.qq.com/s/{open_calls[-1][1]}",
                "record_type": "article-detail",
                "collect_time": "2026-06-21 10:00:00",
                "collect_status": "saved",
            },
            build_failed_record=build_failed_public_article_record,
        )

        event_queue = Queue()
        run_article_capture_flow(
            event_queue,
            {
                "account_name": "account-a",
                "enable_home_article_click": True,
                "run_options": {"recordLimit": 1, "selections": {"articleDetail": True}},
            },
            Queue(),
            deps,
        )

        self.assertEqual(open_calls, [(1, "未保存C")])
        self.assertEqual(saved_records[0]["article_title"], "未保存C")
        self.assertEqual(cursor_holder["cursor"].skip_calls, ["已保存A", "已保存B"])

    def test_flow_records_success_duration_from_click_start_until_sqlite_saved(self) -> None:
        from src.workers.article_capture_flow import ArticleCaptureDependencies, run_article_capture_flow

        saved_records: list[dict] = []

        class FakeCandidate:
            title = "耗时文章"
            article_index = 1
            rect = (100, 100, 500, 140)
            hwnd = 200

        class FakeCursor:
            def __init__(self, *_args, **_kwargs) -> None:
                self.items = [FakeCandidate()]

            def next_candidate(self):
                if not self.items:
                    return None
                return self.items.pop(0)

        class FakeStore:
            def has_saved_public_article_title(self, _account_name: str, _title: str) -> bool:
                return False

            def save_public_article(self, record: dict) -> None:
                saved_records.append(record)

        def put_event(event_queue, level, message, **kwargs):
            event_queue.put({"level": level, "message": message, **kwargs})

        deps = ArticleCaptureDependencies(
            put_event=put_event,
            create_public_article_store=lambda _path: FakeStore(),
            find_wechat_home_window=lambda: FakeHomeWindow(),
            home_article_cursor_cls=FakeCursor,
            open_home_article_for_capture=lambda **_kwargs: {
                "target_title": "耗时文章",
                "click_started_at": time.time() - 1.0,
                "click_result": {"ok": True},
            },
            close_detail_windows=lambda **_kwargs: {"ok": True, "closed": [], "skipped": [], "errors": []},
            click_home_article=lambda *_args, **_kwargs: {"ok": True},
            write_probe=lambda *_args, **_kwargs: None,
            drain_capture_events=lambda _queue: 0,
            collect_report=lambda *_args, **_kwargs: {"ready": True},
            resolve_timeout=lambda _config: 1.0,
            is_report_ready=lambda _report: True,
            resolve_failure_reason=lambda _report: "",
            resolve_failure_title=lambda _report, title, _index: title,
            build_ready_message=lambda _report: "ready",
            get_capture_source=lambda _report: "test",
            build_archive=lambda *_args, **_kwargs: {"archive": True},
            build_record=lambda _archive: {
                "account_name": "account-a",
                "article_title": "耗时文章",
                "published_article_time": "2026-06-21 10:00",
                "article_link": "https://mp.weixin.qq.com/s/duration",
                "record_type": "文章详情",
                "collect_time": "2026-06-21 10:00:00",
                "duration_seconds": 0,
                "collect_status": "saved",
            },
            build_failed_record=build_failed_public_article_record,
        )

        run_article_capture_flow(
            Queue(),
            {
                "account_name": "account-a",
                "enable_home_article_click": True,
                "run_options": {"recordLimit": 1, "selections": {"articleDetail": True}},
            },
            Queue(),
            deps,
        )

        self.assertEqual(len(saved_records), 1)
        self.assertGreaterEqual(saved_records[0]["duration_seconds"], 1.0)

    def test_flow_waits_and_continues_when_home_becomes_unreadable_mid_run(self) -> None:
        from src.workers.article_capture_flow import ArticleCaptureDependencies, run_article_capture_flow

        saved_records: list[dict] = []
        open_calls: list[int] = []
        cursor_creations = {"count": 0}

        class FakeCandidate:
            def __init__(self, title: str, article_index: int) -> None:
                self.title = title
                self.article_index = article_index
                self.rect = (100, 100, 500, 140)
                self.hwnd = 200

        class FakeCursor:
            def __init__(self, *_args, **_kwargs) -> None:
                cursor_creations["count"] += 1
                self.last_stop_reason = ""
                if cursor_creations["count"] == 1:
                    self.items = [FakeCandidate("first", 1)]
                    self.stop_as_unreadable = True
                elif cursor_creations["count"] == 2:
                    self.items = [FakeCandidate("second", 2)]
                    self.stop_as_unreadable = False
                else:
                    self.items = []
                    self.stop_as_unreadable = False

            @property
            def has_visible_candidates(self) -> bool:
                return bool(self.items)

            @property
            def visible_candidates(self):
                return list(self.items)

            def invalidate(self) -> None:
                self.items = []
                self.last_stop_reason = "no_visible_candidates" if self.stop_as_unreadable else "unchanged_after_scroll"

            def next_candidate(self):
                if not self.items:
                    return None
                return self.items.pop(0)

        class FakeStore:
            def has_saved_public_article_title(self, _account_name: str, _title: str) -> bool:
                return False

            def save_public_article(self, record: dict) -> None:
                saved_records.append(record)

        def put_event(event_queue, level, message, **kwargs):
            event_queue.put({"level": level, "message": message, **kwargs})

        def open_article(**kwargs):
            index = int(kwargs["article_index"])
            open_calls.append(index)
            return {"target_title": f"article-{index}", "click_started_at": time.time(), "click_result": {"ok": True}}

        deps = ArticleCaptureDependencies(
            put_event=put_event,
            create_public_article_store=lambda _path: FakeStore(),
            find_wechat_home_window=lambda: FakeHomeWindow(),
            home_article_cursor_cls=FakeCursor,
            open_home_article_for_capture=open_article,
            close_detail_windows=lambda **_kwargs: {"ok": True, "closed": [], "skipped": [], "errors": []},
            click_home_article=lambda *_args, **_kwargs: {"ok": True},
            write_probe=lambda *_args, **_kwargs: None,
            drain_capture_events=lambda _queue: 0,
            collect_report=lambda *_args, **_kwargs: {"ready": True},
            resolve_timeout=lambda _config: 1.0,
            is_report_ready=lambda _report: True,
            resolve_failure_reason=lambda _report: "",
            resolve_failure_title=lambda _report, title, _index: title,
            build_ready_message=lambda _report: "ready",
            get_capture_source=lambda _report: "test",
            build_archive=lambda *_args, **_kwargs: {"archive": True},
            build_record=lambda _archive: {
                "account_name": "account-a",
                "article_title": f"saved-{len(saved_records) + 1}",
                "published_article_time": "2026-06-21 10:00",
                "article_link": f"https://mp.weixin.qq.com/s/{len(saved_records) + 1}",
                "record_type": "article-detail",
                "collect_time": "2026-06-21 10:00:00",
                "collect_status": "saved",
            },
            build_failed_record=build_failed_public_article_record,
        )

        event_queue = Queue()
        run_article_capture_flow(
            event_queue,
            {
                "account_name": "测试公众号",
                "enable_home_article_click": True,
                "homepage_candidate_wait_timeout_seconds": 1,
                "homepage_candidate_wait_interval_seconds": 0,
                "run_options": {"recordLimit": 2, "selections": {"articleDetail": True}},
            },
            Queue(),
            deps,
        )

        self.assertEqual(open_calls, [1, 2])
        self.assertEqual(len(saved_records), 2)
        messages = [item.get("message", "") for item in drain_queue(event_queue)]
        self.assertTrue(any("主页窗口已恢复可读" in message for message in messages), messages)

    def test_flow_relocates_home_window_before_waiting_for_candidates(self) -> None:
        from src.workers.article_capture_flow import ArticleCaptureDependencies, run_article_capture_flow

        saved_records: list[dict] = []
        open_calls: list[int] = []
        cursor_windows: list[int] = []
        find_calls = {"count": 0}

        class FakeCandidate:
            def __init__(self, title: str, article_index: int) -> None:
                self.title = title
                self.article_index = article_index
                self.rect = (100, 100, 500, 140)
                self.hwnd = 200

        class FakeCursor:
            def __init__(self, *_args, **kwargs) -> None:
                home_window = kwargs.get("home_window")
                hwnd = int(getattr(home_window, "NativeWindowHandle", 0) or 0)
                cursor_windows.append(hwnd)
                self.last_stop_reason = ""
                self.items = [FakeCandidate("first", 1)] if len(cursor_windows) == 1 else []
                if hwnd == 202:
                    self.items = [FakeCandidate("second", 2)]

            @property
            def has_visible_candidates(self) -> bool:
                return bool(self.items)

            @property
            def visible_candidates(self):
                return list(self.items)

            def invalidate(self) -> None:
                self.items = []
                self.last_stop_reason = "no_visible_candidates"

            def next_candidate(self):
                if not self.items:
                    self.last_stop_reason = self.last_stop_reason or "no_visible_candidates"
                    return None
                return self.items.pop(0)

        class FakeStore:
            def has_saved_public_article_title(self, _account_name: str, _title: str) -> bool:
                return False

            def save_public_article(self, record: dict) -> None:
                saved_records.append(record)

        def find_home_window():
            find_calls["count"] += 1
            return FakeHomeWindow(101 if find_calls["count"] == 1 else 202)

        def put_event(event_queue, level, message, **kwargs):
            event_queue.put({"level": level, "message": message, **kwargs})

        def open_article(**kwargs):
            index = int(kwargs["article_index"])
            open_calls.append(index)
            return {"target_title": f"article-{index}", "click_started_at": time.time(), "click_result": {"ok": True}}

        deps = ArticleCaptureDependencies(
            put_event=put_event,
            create_public_article_store=lambda _path: FakeStore(),
            find_wechat_home_window=find_home_window,
            home_article_cursor_cls=FakeCursor,
            open_home_article_for_capture=open_article,
            close_detail_windows=lambda **_kwargs: {"ok": True, "closed": [], "skipped": [], "errors": []},
            click_home_article=lambda *_args, **_kwargs: {"ok": True},
            write_probe=lambda *_args, **_kwargs: None,
            drain_capture_events=lambda _queue: 0,
            collect_report=lambda *_args, **_kwargs: {"ready": True},
            resolve_timeout=lambda _config: 1.0,
            is_report_ready=lambda _report: True,
            resolve_failure_reason=lambda _report: "",
            resolve_failure_title=lambda _report, title, _index: title,
            build_ready_message=lambda _report: "ready",
            get_capture_source=lambda _report: "test",
            build_archive=lambda *_args, **_kwargs: {"archive": True},
            build_record=lambda _archive: {
                "account_name": "account-a",
                "article_title": f"saved-{len(saved_records) + 1}",
                "published_article_time": "2026-06-21 10:00",
                "article_link": f"https://mp.weixin.qq.com/s/{len(saved_records) + 1}",
                "record_type": "article-detail",
                "collect_time": "2026-06-21 10:00:00",
                "collect_status": "saved",
            },
            build_failed_record=build_failed_public_article_record,
        )

        run_article_capture_flow(
            Queue(),
            {
                "account_name": "测试公众号",
                "enable_home_article_click": True,
                "homepage_candidate_wait_timeout_seconds": 0,
                "homepage_candidate_wait_interval_seconds": 0,
                "run_options": {"recordLimit": 2, "selections": {"articleDetail": True}},
            },
            Queue(),
            deps,
        )

        self.assertEqual(open_calls, [1, 2])
        self.assertGreaterEqual(find_calls["count"], 2)
        self.assertIn(202, cursor_windows)
        self.assertEqual(len(saved_records), 2)

    def test_capture_ready_message_distinguishes_referer_fallback(self) -> None:
        report = {
            "main_html_capture": {
                "source": "mitm_referer_fallback",
                "url": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=key",
            }
        }

        message = article_capture.build_capture_ready_message(report)

        self.assertIn("Referer", message)
        self.assertIn("requests 保底", message)
        self.assertNotIn("主 HTML", message)

    def test_mitm_wait_timeout_does_not_refresh_article_window(self) -> None:
        refresh_calls = 0

        def refresh_callback() -> dict:
            nonlocal refresh_calls
            refresh_calls += 1
            return {"ok": True, "reason": "should_not_refresh"}

        report = collect_article_capture_report_from_mitm(
            Queue(),
            {"account_name": "测试公众号"},
            article_index=1,
            timeout_seconds=0.03,
            idle_refresh_seconds=0.01,
            idle_callback=refresh_callback,
        )

        self.assertEqual(refresh_calls, 0)
        self.assertIn("等待 MITM 捕获文章主 HTML 超时", report["automation_error"])
        self.assertNotIn("刷新", report["automation_error"])

    def test_mitm_tunnel_candidate_does_not_refresh_article_window(self) -> None:
        refresh_calls = 0
        capture_queue = Queue()
        capture_queue.put(
            {
                "type": "article_main_html_candidate",
                "reason": "wechat_tunnel_seen",
                "url_redacted": "https://mp.weixin.qq.com/",
                "query_keys": [],
                "status_code": 0,
                "content_type": "",
                "body_chars": 0,
            }
        )

        def refresh_callback() -> dict:
            nonlocal refresh_calls
            refresh_calls += 1
            return {"ok": True, "reason": "should_not_refresh"}

        report = collect_article_capture_report_from_mitm(
            capture_queue,
            {"account_name": "测试公众号"},
            article_index=1,
            timeout_seconds=0.03,
            idle_refresh_seconds=0.01,
            idle_callback=refresh_callback,
        )

        self.assertEqual(refresh_calls, 0)
        self.assertIn("MITM 已看到微信 HTTPS 隧道", report["automation_error"])
        self.assertNotIn("刷新", report["automation_error"])

    def test_mitm_wait_records_request_stage_article_url_before_html_timeout(self) -> None:
        capture_queue = Queue()
        capture_queue.put(
            {
                "type": "article_main_html_requested",
                "url_redacted": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn",
                "host": "mp.weixin.qq.com",
                "path": "/s",
                "method": "GET",
                "query_keys": ["__biz", "idx", "key", "mid", "sn"],
                "createdAt": "2026-06-19T16:20:00",
            }
        )

        report = collect_article_capture_report_from_mitm(
            capture_queue,
            {"account_name": "测试公众号"},
            article_index=1,
            timeout_seconds=0.03,
        )

        self.assertIn("request 阶段", report["automation_error"])
        self.assertIn("没有收到可保存的 response HTML", report["automation_error"])
        self.assertEqual(report["mitm_diagnostics"][0]["reason"], "article_main_html_requested")

    def test_mitm_wait_builds_fallback_for_real_request_without_response(self) -> None:
        capture_queue = Queue()
        capture_queue.put(
            {
                "type": "article_main_html_requested",
                "url": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret",
                "url_redacted": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn",
                "host": "mp.weixin.qq.com",
                "path": "/s",
                "method": "GET",
                "query": {"__biz": ["biz"], "mid": ["1"], "idx": ["1"], "sn": ["sn"], "key": ["secret"]},
                "query_keys": ["__biz", "idx", "key", "mid", "sn"],
                "request_headers": {"user-agent": "MicroMessenger"},
                "timestamp": 100.0,
                "createdAt": "2026-06-19T16:20:00",
            }
        )
        report = collect_article_capture_report_from_mitm(
            capture_queue,
            {
                "account_name": "测试公众号",
            },
            article_index=1,
            timeout_seconds=0.03,
        )

        self.assertNotIn("automation_error", report)
        self.assertTrue(is_report_ready_for_article_storage(report))
        self.assertEqual(report["main_html_capture"]["source"], "mitm_keyed_url_fallback")
        self.assertEqual(report["main_html_capture"]["url_source"], "request")
        self.assertEqual(report["main_html_capture"]["url"], "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret")
        self.assertEqual(report["mitm_diagnostics"][0]["reason"], "article_main_html_requested")

    def test_mitm_wait_builds_fallback_report_for_referer_keyed_url(self) -> None:
        capture_queue = Queue()
        capture_queue.put(
            {
                "type": "article_main_html_requested",
                "url": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret",
                "url_redacted": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn",
                "host": "mp.weixin.qq.com",
                "path": "/s",
                "method": "GET",
                "query": {"__biz": ["biz"], "mid": ["1"], "idx": ["1"], "sn": ["sn"], "key": ["secret"]},
                "query_keys": ["__biz", "idx", "key", "mid", "sn"],
                "request_headers": {"user-agent": "MicroMessenger", "referer": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret"},
                "url_source": "referer",
                "carrier_url_redacted": "https://mp.weixin.qq.com/mp/geticon?biz=biz",
                "timestamp": 100.0,
                "createdAt": "2026-06-19T16:20:00",
            }
        )

        report = collect_article_capture_report_from_mitm(
            capture_queue,
            {"account_name": "测试公众号"},
            article_index=1,
            timeout_seconds=1,
            target_title="Referer 文章",
        )

        self.assertNotIn("automation_error", report)
        self.assertTrue(is_report_ready_for_article_storage(report))
        self.assertEqual(report["main_html_capture"]["url"], "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret")
        self.assertEqual(report["main_html_capture"]["url_source"], "referer")
        self.assertEqual(report["main_html_capture"]["source"], "mitm_referer_fallback")
        self.assertEqual(report["main_html_capture"]["request_headers"]["user-agent"], "MicroMessenger")

    def test_mitm_wait_returns_referer_fallback_as_soon_as_keyed_url_is_seen(self) -> None:
        capture_queue = Queue()
        capture_queue.put(
            {
                "type": "article_main_html_requested",
                "url": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret",
                "url_redacted": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn",
                "host": "mp.weixin.qq.com",
                "path": "/s",
                "method": "GET",
                "query": {"__biz": ["biz"], "mid": ["1"], "idx": ["1"], "sn": ["sn"], "key": ["secret"]},
                "query_keys": ["__biz", "idx", "key", "mid", "sn"],
                "request_headers": {"user-agent": "MicroMessenger"},
                "url_source": "referer",
                "timestamp": 100.0,
            }
        )

        started_at = time.perf_counter()
        report = collect_article_capture_report_from_mitm(
            capture_queue,
            {"account_name": "测试公众号"},
            article_index=1,
            timeout_seconds=0.5,
            target_title="主页文章标题",
        )
        elapsed_seconds = time.perf_counter() - started_at

        self.assertLess(elapsed_seconds, 0.2)
        self.assertEqual(report["main_html_capture"]["source"], "mitm_referer_fallback")
        self.assertEqual(report["target_article"]["title"], "主页文章标题")

    def test_mitm_wait_returns_confirmed_referer_fallback_without_waiting_for_timeout(self) -> None:
        capture_queue = Queue()
        capture_queue.put(
            {
                "type": "article_main_html_requested",
                "url": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret",
                "url_redacted": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn",
                "host": "mp.weixin.qq.com",
                "path": "/s",
                "method": "GET",
                "query": {"__biz": ["biz"], "mid": ["1"], "idx": ["1"], "sn": ["sn"], "key": ["secret"]},
                "query_keys": ["__biz", "idx", "key", "mid", "sn"],
                "request_headers": {"user-agent": "MicroMessenger"},
                "url_source": "referer",
                "carrier_url_redacted": "https://mp.weixin.qq.com/mp/geticon?biz=biz",
                "timestamp": 100.0,
            }
        )
        capture_queue.put(
            {
                "type": "article_main_html_candidate",
                "reason": "wechat_response_target_title_seen",
                "url_redacted": "https://mp.weixin.qq.com/mp/tts?action=getttslistenitem",
                "host": "mp.weixin.qq.com",
                "path": "/mp/tts",
                "method": "GET",
                "status_code": 200,
                "content_type": "application/json; charset=utf-8",
                "body_chars": 1024,
                "title": "目标文章标题",
                "title_candidates": ["目标文章标题"],
                "title_matched": True,
                "timestamp": 100.1,
            }
        )

        started_at = time.perf_counter()
        report = collect_article_capture_report_from_mitm(
            capture_queue,
            {"account_name": "测试公众号"},
            article_index=1,
            timeout_seconds=0.5,
            target_title="目标文章标题",
        )
        elapsed_seconds = time.perf_counter() - started_at

        self.assertLess(elapsed_seconds, 0.2)
        self.assertNotIn("automation_error", report)
        self.assertEqual(report["main_html_capture"]["source"], "mitm_referer_fallback")
        self.assertEqual(report["main_html_capture"]["url_source"], "referer")

    def test_mitm_wait_returns_referer_fallback_before_later_title_mismatch_diagnostic(self) -> None:
        capture_queue = Queue()
        capture_queue.put(
            {
                "type": "article_main_html_requested",
                "url": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret",
                "url_redacted": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn",
                "host": "mp.weixin.qq.com",
                "path": "/s",
                "method": "GET",
                "query_keys": ["__biz", "idx", "key", "mid", "sn"],
                "request_headers": {"user-agent": "MicroMessenger"},
                "url_source": "referer",
                "timestamp": 100.0,
            }
        )
        capture_queue.put(
            {
                "type": "article_main_html_candidate",
                "reason": "wechat_response_target_title_seen",
                "url_redacted": "https://mp.weixin.qq.com/mp/tts?action=getttslistenitem",
                "host": "mp.weixin.qq.com",
                "path": "/mp/tts",
                "method": "GET",
                "status_code": 200,
                "content_type": "application/json; charset=utf-8",
                "body_chars": 1024,
                "title": "其他文章标题",
                "title_candidates": ["其他文章标题"],
                "title_matched": True,
                "timestamp": 100.1,
            }
        )

        started_at = time.perf_counter()
        report = collect_article_capture_report_from_mitm(
            capture_queue,
            {"account_name": "测试公众号"},
            article_index=1,
            timeout_seconds=0.08,
            target_title="目标文章标题",
        )
        elapsed_seconds = time.perf_counter() - started_at

        self.assertLess(elapsed_seconds, 0.2)
        self.assertEqual(report["main_html_capture"]["source"], "mitm_referer_fallback")
        self.assertEqual(len(report["mitm_diagnostics"]), 1)

    def test_mitm_wait_reports_response_title_matching_clicked_article(self) -> None:
        capture_queue = Queue()
        capture_queue.put(
            {
                "type": "article_main_html_candidate",
                "reason": "article_html_without_key_ignored",
                "url_redacted": "https://mp.weixin.qq.com/s/shortLink123",
                "host": "mp.weixin.qq.com",
                "path": "/s/shortLink123",
                "method": "GET",
                "status_code": 200,
                "content_type": "text/html; charset=utf-8",
                "body_chars": 4096,
                "title": "target article title",
                "title_matched": True,
                "timestamp": 100.0,
            }
        )

        report = collect_article_capture_report_from_mitm(
            capture_queue,
            {"account_name": "test account"},
            article_index=1,
            timeout_seconds=0.03,
            target_title="target article title",
        )

        self.assertTrue(report["mitm_diagnostics"][0]["title_matches_target"])
        self.assertIn("matches clicked title", report["automation_error"])
        self.assertIn("target article title", report["automation_error"])

    def test_mitm_wait_ignores_stale_request_events_before_click_start(self) -> None:
        capture_queue = Queue()
        capture_queue.put(
            {
                "type": "article_main_html_requested",
                "url": "https://mp.weixin.qq.com/s?__biz=old&mid=1&idx=1&sn=old&key=old",
                "url_redacted": "https://mp.weixin.qq.com/s?__biz=old&mid=1&idx=1&sn=old",
                "host": "mp.weixin.qq.com",
                "path": "/s",
                "method": "GET",
                "query_keys": ["__biz", "idx", "key", "mid", "sn"],
                "timestamp": 10.0,
            }
        )
        fresh_event = build_mitm_capture_event(short_link="https://mp.weixin.qq.com/s/freshShort1")
        fresh_event["timestamp"] = 20.0
        capture_queue.put(fresh_event)

        report = collect_article_capture_report_from_mitm(
            capture_queue,
            {"account_name": "测试公众号"},
            article_index=1,
            timeout_seconds=1,
            min_event_timestamp=15.0,
        )

        self.assertEqual(report["article_detail"]["article_short_link"], "https://mp.weixin.qq.com/s/freshShort1")

    def test_mitm_timeout_reason_reports_requested_url_without_response_html(self) -> None:
        reason = build_mitm_timeout_reason(
            "等待 MITM 捕获文章主 HTML 超时",
            [
                {
                    "reason": "article_main_html_requested",
                    "url_redacted": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn",
                    "host": "mp.weixin.qq.com",
                    "path": "/s",
                    "query_keys": ["__biz", "idx", "key", "mid", "sn"],
                },
            ],
        )

        self.assertIn("request 阶段", reason)
        self.assertIn("没有收到可保存的 response HTML", reason)

    def test_mitm_timeout_reason_reports_referer_url_is_not_real_main_request(self) -> None:
        reason = build_mitm_timeout_reason(
            "等待 MITM 捕获文章主 HTML 超时",
            [
                {
                    "reason": "wechat_tunnel_seen",
                    "url_redacted": "https://mp.weixin.qq.com/",
                    "host": "mp.weixin.qq.com",
                    "path": "/",
                },
                {
                    "reason": "article_referer_seen",
                    "url_redacted": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn",
                    "host": "mp.weixin.qq.com",
                    "path": "/s",
                    "query_keys": ["__biz", "idx", "key", "mid", "sn"],
                },
            ],
        )

        self.assertIn("只从资源请求 Referer 看到文章主 URL", reason)
        self.assertIn("没有看到微信内置浏览器发出真实文章主请求", reason)

    def test_mitm_timeout_reason_reports_tls_failure_before_cache_hint(self) -> None:
        reason = build_mitm_timeout_reason(
            "等待 MITM 捕获文章主 HTML 超时",
            [
                {
                    "reason": "wechat_tunnel_seen",
                    "url_redacted": "https://mp.weixin.qq.com/",
                },
                {
                    "reason": "tls_client_failed",
                    "url_redacted": "https://mp.weixin.qq.com/",
                    "error": "certificate verify failed",
                },
            ],
        )

        self.assertIn("TLS 解密失败", reason)
        self.assertIn("certificate verify failed", reason)

    def test_mitm_timeout_reason_reports_missing_client_tls_when_only_server_tls_established(self) -> None:
        reason = build_mitm_timeout_reason(
            "等待 MITM 捕获文章主 HTML 超时",
            [
                {
                    "reason": "wechat_tunnel_seen",
                    "url_redacted": "https://mp.weixin.qq.com/",
                    "host": "mp.weixin.qq.com",
                },
                {
                    "reason": "tls_clienthello",
                    "url_redacted": "https://mp.weixin.qq.com/",
                    "host": "mp.weixin.qq.com",
                },
                {
                    "reason": "tls_server_established",
                    "url_redacted": "https://mp.weixin.qq.com/",
                    "host": "mp.weixin.qq.com",
                },
            ],
        )

        self.assertIn("客户端侧 TLS 握手未完成", reason)
        self.assertIn("证书信任", reason)

    def test_mitm_capture_timeout_defaults_to_10_seconds(self) -> None:
        self.assertEqual(resolve_mitm_capture_timeout_seconds({}), 10.0)

    def test_mitm_capture_timeout_over_30_seconds_is_capped_to_10_seconds(self) -> None:
        self.assertEqual(resolve_mitm_capture_timeout_seconds({"mitm_capture_timeout_seconds": 60}), 10.0)

    def test_mitm_timeout_reason_prefers_article_host_over_resource_tunnel(self) -> None:
        reason = build_mitm_timeout_reason(
            "等待 MITM 捕获文章主 HTML 超时",
            [
                {
                    "reason": "wechat_tunnel_seen",
                    "url_redacted": "https://mp.weixin.qq.com/",
                    "host": "mp.weixin.qq.com",
                    "path": "/",
                },
                {
                    "reason": "wechat_tunnel_seen",
                    "url_redacted": "https://res.wx.qq.com/",
                    "host": "res.wx.qq.com",
                    "path": "/",
                },
            ],
        )

        self.assertIn("mp.weixin.qq.com", reason)
        self.assertNotIn("res.wx.qq.com", reason)


def build_mitm_capture_event(short_link: str) -> dict:
    short_link_script = f"window.short_link = '{short_link}';" if short_link else ""
    html_text = f"""
    <html>
      <body>
        <script>
          var msg_title = 'worker测试文章';
          var publish_time = '2026-06-18 18:58';
          {short_link_script}
        </script>
        <div id="js_content">正文内容</div>
      </body>
    </html>
    """
    return {
        "type": "article_main_html_captured",
        "method": "GET",
        "url": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret",
        "url_redacted": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn",
        "query": {"__biz": ["biz"], "mid": ["1"], "idx": ["1"], "sn": ["sn"], "key": ["secret"]},
        "request_headers": {"user-agent": "MicroMessenger"},
        "response_headers": {"content-type": "text/html"},
        "status_code": 200,
        "title": "worker测试文章",
        "published_article_time": "2026-06-18 18:58",
        "article_short_link": short_link,
        "html_text": html_text,
    }


def build_fake_article_detail(short_link: str) -> dict:
    return {
        "account_name": "测试公众号",
        "article_title": "worker测试文章",
        "published_article_time": "2026-06-18 18:58",
        "short_link": short_link,
        "url_redacted": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn",
        "audience_count": None,
        "read_count": 100001,
        "like_count": None,
        "share_count": None,
        "recommend_count": None,
        "comment_count": None,
        "collect_time": "2026-06-18 19:00:00",
    }


def drain_queue(event_queue: Queue) -> list[dict]:
    items: list[dict] = []
    while True:
        try:
            items.append(event_queue.get_nowait())
        except Empty:
            return items


class FakeCaptureQueue:
    """模拟 worker 清空旧事件后，MITM 才捕获到新文章事件。"""

    def __init__(self, event: dict) -> None:
        self.event = event
        self.consumed = False

    def get_nowait(self):
        raise Empty

    def get(self, timeout: float | None = None):
        if self.consumed:
            raise Empty
        self.consumed = True
        return self.event


class FakeHttpRequest:
    def __init__(self, url: str) -> None:
        self.pretty_url = url
        self.method = "GET"
        self.headers = {}


class FakeHttpResponse:
    def __init__(self, html_text: str) -> None:
        self.status_code = 200
        self.headers = {"content-type": "text/html; charset=utf-8"}
        self.raw_content = html_text.encode("utf-8")

    def get_text(self, strict: bool = False) -> str:
        return self.raw_content.decode("utf-8")


class FakeHttpFlow:
    def __init__(self, url: str, html_text: str) -> None:
        self.request = FakeHttpRequest(url)
        self.response = FakeHttpResponse(html_text)


class FakeTlsClientHello:
    def __init__(self, sni: str) -> None:
        self.sni = sni
        self.alpn_protocols = [b"h2", b"http/1.1"]


class FakeTlsClientHelloData:
    def __init__(self, sni: str) -> None:
        self.client_hello = FakeTlsClientHello(sni)


class FakeTlsConn:
    def __init__(self, sni: str, error: str = "") -> None:
        self.sni = sni
        self.error = error
        self.address = (sni, 443)
        self.alpn = b"h2"
        self.tls_version = "TLSv1.3"


class FakeTlsData:
    def __init__(self, sni: str, error: str = "") -> None:
        self.conn = FakeTlsConn(sni, error=error)


if __name__ == "__main__":
    unittest.main()

