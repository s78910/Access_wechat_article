from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from src.modules.detail.article_detail import (
    ArticleDetailFetchError,
    build_keyed_article_url,
    build_article_detail_from_html,
    fetch_article_detail_to_file,
    normalize_request_headers,
)


class ArticleDetailFetcherTest(unittest.TestCase):
    def test_request_article_html_uses_direct_session_without_system_proxy(self) -> None:
        from src.modules.detail.article_detail import request_article_html

        class FakeResponse:
            status_code = 200
            text = "<html>ok</html>"

        class FakeSession:
            def __init__(self) -> None:
                self.trust_env = True
                self.get_calls: list[dict[str, object]] = []

            def get(self, url: str, **kwargs):
                self.get_calls.append({"url": url, **kwargs})
                return FakeResponse()

        fake_session = FakeSession()

        with patch("requests.Session", return_value=fake_session):
            html_text = request_article_html(
                "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret",
                request_headers={
                    "User-Agent": "MicroMessenger/8.0",
                    "Host": "mp.weixin.qq.com",
                },
                timeout_seconds=5,
            )

        self.assertEqual(html_text, "<html>ok</html>")
        self.assertFalse(fake_session.trust_env)
        self.assertEqual(len(fake_session.get_calls), 1)
        call = fake_session.get_calls[0]
        self.assertEqual(call["headers"], {"user-agent": "MicroMessenger/8.0"})
        self.assertEqual(call["timeout"], 5.0)
        self.assertEqual(call["proxies"], {"http": None, "https": None})

    def test_fetch_keyed_url_writes_only_structured_article_detail(self) -> None:
        html_text = """
        <html><body>
          <script>
            var nickname = '测试公众号';
            var msg_title = '测试文章标题';
            var publish_time = '2026-06-19 21:39';
            window.short_link = 'https://mp.weixin.qq.com/s/testShort123';
            var appmsgBarData = {
              tts_heard_person_cnt: '2998' * 1,
              read_num: '100001' * 1,
              old_like_count: '6006' * 1,
              share_count: '33513' * 1,
              like_count: '2450' * 1,
              comment_count: '11' * 1
            };
          </script>
        </body></html>
        """
        requested: dict[str, object] = {}

        def fake_fetch_html(url: str, headers: dict[str, str], timeout_seconds: float) -> str:
            requested["url"] = url
            requested["headers"] = headers
            requested["timeout_seconds"] = timeout_seconds
            return html_text

        with tempfile.TemporaryDirectory() as temp_dir:
            article_dir = Path(temp_dir) / "storages" / "测试公众号" / "2026-06-19 21-39 测试文章标题"
            result = fetch_article_detail_to_file(
                "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret&pass_ticket=ticket",
                article_dir,
                request_headers={"user-agent": "MicroMessenger"},
                collect_time="2026-06-19 22:00:00",
                fetch_html=fake_fetch_html,
            )

            detail_path = Path(result["article_detail_path"])
            detail = json.loads(detail_path.read_text(encoding="utf-8"))
            runtime_detail = result["detail"]

        self.assertEqual(detail_path.name, "article_detail.json")
        self.assertEqual(detail_path.parent.name, "2026-06-19 21-39 测试文章标题")
        self.assertEqual(requested["url"], "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret&pass_ticket=ticket")
        self.assertEqual(requested["headers"], {"user-agent": "MicroMessenger"})
        self.assertEqual(
            set(detail),
            {
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
            },
        )
        self.assertEqual(detail["account_name"], "测试公众号")
        self.assertEqual(detail["article_title"], "测试文章标题")
        self.assertEqual(detail["published_article_time"], "2026-06-19 21:39")
        self.assertEqual(detail["short_link"], "https://mp.weixin.qq.com/s/testShort123")
        self.assertNotIn("secret", detail["url_redacted"])
        self.assertNotIn("pass_ticket=ticket", detail["url_redacted"])
        self.assertEqual(detail["audience_count"], 2998)
        self.assertEqual(detail["read_count"], 100001)
        self.assertEqual(detail["like_count"], 6006)
        self.assertEqual(detail["share_count"], 33513)
        self.assertEqual(detail["recommend_count"], 2450)
        self.assertEqual(detail["comment_count"], 11)
        self.assertEqual(detail["collect_time"], "2026-06-19 22:00:00")
        self.assertIn("_source_html", runtime_detail)
        self.assertIn("https://mp.weixin.qq.com/s/testShort123", runtime_detail["_source_html"])
        self.assertNotIn("_source_html", detail)

    def test_account_name_ignores_miniprogram_attribute_placeholder(self) -> None:
        html_text = """
        <html><head>
          <meta name="author" content="data-miniprogram-nickname">
        </head><body>
          <a id="js_name">新华社</a>
          <script>
            var msg_title = '世界杯首张“捂嘴红牌”，诞生';
            var publish_time = '2026-06-20 14:45';
            window.short_link = 'https://mp.weixin.qq.com/s/testRealAccount123';
          </script>
        </body></html>
        """

        detail = build_article_detail_from_html(
            html_text,
            "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret",
            collect_time="2026-06-21 14:10:00",
        )

        self.assertEqual(detail["account_name"], "新华社")
        self.assertNotEqual(detail["account_name"], "data-miniprogram-nickname")

    def test_fetch_keyed_url_without_short_link_does_not_write_detail_file(self) -> None:
        def fake_fetch_html(_url: str, _headers: dict[str, str], _timeout_seconds: float) -> str:
            return "<script>var msg_title='无短链文章'; var publish_time='2026-06-19 21:39';</script>"

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            with self.assertRaises(ArticleDetailFetchError):
                fetch_article_detail_to_file(
                    "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret",
                    output_dir,
                    fetch_html=fake_fetch_html,
                )

            self.assertFalse((output_dir / "article_detail.json").exists())

    def test_build_keyed_article_url_keeps_required_runtime_parameters(self) -> None:
        url = build_keyed_article_url(
            "__biz-value",
            "123",
            "1",
            "sn-value",
            "key-value",
            pass_ticket="ticket-value",
        )
        query = parse_qs(urlparse(url).query)

        self.assertEqual(query["__biz"], ["__biz-value"])
        self.assertEqual(query["mid"], ["123"])
        self.assertEqual(query["idx"], ["1"])
        self.assertEqual(query["sn"], ["sn-value"])
        self.assertEqual(query["key"], ["key-value"])
        self.assertEqual(query["pass_ticket"], ["ticket-value"])

    def test_normalize_request_headers_keeps_real_browser_context_headers(self) -> None:
        headers = normalize_request_headers(
            {
                ":method": "GET",
                ":authority": "mp.weixin.qq.com",
                "Host": "mp.weixin.qq.com",
                "Connection": "keep-alive",
                "Content-Length": "123",
                "User-Agent": "MicroMessenger/8.0",
                "Cookie": "session=abc",
                "Referer": "https://mp.weixin.qq.com/",
                "Accept": "text/html",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Sec-Fetch-Site": "same-origin",
                "X-Requested-With": "com.tencent.mm",
            }
        )

        self.assertEqual(headers["user-agent"], "MicroMessenger/8.0")
        self.assertEqual(headers["cookie"], "session=abc")
        self.assertEqual(headers["sec-fetch-site"], "same-origin")
        self.assertEqual(headers["x-requested-with"], "com.tencent.mm")
        self.assertNotIn(":method", headers)
        self.assertNotIn(":authority", headers)
        self.assertNotIn("host", headers)
        self.assertNotIn("connection", headers)
        self.assertNotIn("content-length", headers)


if __name__ == "__main__":
    unittest.main()
