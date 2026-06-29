from __future__ import annotations

import unittest

from tests.tools.article_detail_probe import (
    build_getappmsgext_request,
    extract_detail_runtime_context,
    extract_metric_assignments_from_html,
    normalize_metric_payload,
)


class ArticleDetailProbeTest(unittest.TestCase):
    def test_extract_detail_runtime_context_from_html_and_url(self) -> None:
        html_text = """
        <script>
          var brokenBiz = ").concat(opts.biz,";
          var appmsg_token = "token-from-html";
          var pass_ticket = "ticket-from-html";
          var msg_title = '测试标题';
          var publish_time = '2026-06-19 21:39';
          var appmsgid = "123456";
          var itemidx = "1";
          var sn = "sn-from-html";
        </script>
        """
        url = "https://mp.weixin.qq.com/s?__biz=biz-from-url&mid=123456&idx=1&sn=sn-from-url&key=secret"

        context = extract_detail_runtime_context(url, html_text)

        self.assertEqual(context["__biz"], "biz-from-url")
        self.assertEqual(context["mid"], "123456")
        self.assertEqual(context["idx"], "1")
        self.assertEqual(context["sn"], "sn-from-url")
        self.assertEqual(context["appmsg_token"], "token-from-html")
        self.assertEqual(context["pass_ticket"], "ticket-from-html")
        self.assertEqual(context["article_title"], "测试标题")
        self.assertEqual(context["published_article_time"], "2026-06-19 21:39")

    def test_extract_detail_runtime_context_ignores_template_biz_fragments(self) -> None:
        html_text = """<script>var biz = ").concat(opts.biz,"; var appmsgid = "123";</script>"""
        url = "https://mp.weixin.qq.com/s?__biz=real-biz&mid=123&idx=1&sn=real-sn"

        context = extract_detail_runtime_context(url, html_text)

        self.assertEqual(context["__biz"], "real-biz")

    def test_extract_detail_runtime_context_keeps_url_article_identity_over_html_noise(self) -> None:
        html_text = """
        <script>
          var appmsgid = "2650221595";
          var itemidx = "1";
          var voice_in_appmsg = {
            "voice-id": { sn: "voice-sn-not-article-sn" }
          };
        </script>
        """
        url = "https://mp.weixin.qq.com/s?__biz=biz-from-url&mid=2650221595&idx=1&sn=article-sn-from-url"

        context = extract_detail_runtime_context(url, html_text)

        self.assertEqual(context["__biz"], "biz-from-url")
        self.assertEqual(context["mid"], "2650221595")
        self.assertEqual(context["idx"], "1")
        self.assertEqual(context["sn"], "article-sn-from-url")

    def test_extract_metric_assignments_from_html_ignores_empty_wechat_placeholders(self) -> None:
        html_text = """
        <script>
          var read_num = "" * 1;
          var tts_heard_person_cnt = '' * 1 || 0;
          var appmsgBarData = {
            old_like_count: '6006' * 1,
            share_count: '33513' * 1,
            like_count: '2450' * 1,
            comment_count: '11' * 1,
            read_num: '100001' * 1
          };
        </script>
        """

        assignments = extract_metric_assignments_from_html(html_text)

        self.assertNotIn("tts_heard_person_cnt", assignments)
        self.assertEqual(assignments["read_num"], 100001)
        self.assertEqual(assignments["old_like_count"], 6006)
        self.assertEqual(assignments["share_count"], 33513)
        self.assertEqual(assignments["like_count"], 2450)
        self.assertEqual(assignments["comment_count"], 11)

    def test_build_getappmsgext_request_uses_runtime_context_and_headers(self) -> None:
        context = {
            "__biz": "biz-value",
            "mid": "123456",
            "idx": "1",
            "sn": "sn-value",
            "appmsg_token": "token-value",
            "pass_ticket": "ticket-value",
            "key": "key-value",
        }
        request_headers = {
            "user-agent": "MicroMessenger",
            "cookie": "uin=1; pass_ticket=old",
            "accept": "text/html",
            "referer": "https://mp.weixin.qq.com/s?__biz=biz-value",
        }

        request = build_getappmsgext_request(context, request_headers)

        self.assertEqual(request["method"], "POST")
        self.assertIn("/mp/getappmsgext", request["url"])
        self.assertIn("f=json", request["url"])
        self.assertEqual(request["headers"]["user-agent"], "MicroMessenger")
        self.assertEqual(request["headers"]["x-requested-with"], "XMLHttpRequest")
        self.assertIn("__biz=biz-value", request["data"])
        self.assertIn("appmsgid=123456", request["data"])
        self.assertIn("itemidx=1", request["data"])

    def test_normalize_metric_payload_collects_known_counter_fields(self) -> None:
        payload = {
            "appmsgstat": {
                "read_num": 100001,
                "old_like_num": 6006,
                "like_num": 2450,
                "share_num": 33513,
                "comment_count": 11,
            },
            "tts_heard_person_cnt": 2998,
        }

        metrics = normalize_metric_payload(payload)

        self.assertEqual(metrics["read_count"], 100001)
        self.assertEqual(metrics["like_count"], 6006)
        self.assertEqual(metrics["recommend_count"], 2450)
        self.assertEqual(metrics["share_count"], 33513)
        self.assertEqual(metrics["comment_count"], 11)
        self.assertEqual(metrics["audience_count"], 2998)


if __name__ == "__main__":
    unittest.main()
