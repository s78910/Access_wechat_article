from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src.modules.detail.comment_detail import (
    build_comment_page_url,
    fetch_comments_to_archive,
    normalize_comment_request_headers,
)


class CommentFetcherTest(unittest.TestCase):
    def test_fetch_comments_pages_replies_and_resources_to_article_dir(self) -> None:
        keyed_url = (
            "https://mp.weixin.qq.com/s?__biz=biz-value&mid=123&idx=1&sn=sn-value"
            "&key=key-secret&pass_ticket=ticket-secret&appmsg_token=token-secret&uin=777"
        )
        html_text = """
        <html><body>
          <script>
            var nickname = '测试公众号';
            var msg_title = '测试文章';
            var publish_time = '2026-06-19 21:39';
            var comment_id = 'comment-abc';
            var appmsg_token = 'token-from-html';
          </script>
        </body></html>
        """
        requested_urls: list[str] = []
        requested_headers: list[dict[str, str]] = []

        first_page = {
            "base_resp": {"ret": 0, "errmsg": "ok"},
            "continue_flag": 1,
            "buffer": "next-buffer",
            "elected_comment_total_cnt": 2,
            "elected_comment": [
                {
                    "id": "c1",
                    "content_id": "content-1",
                    "nick_name": "张三",
                    "logo_url": "https://mmbiz.qpic.cn/avatar/one.jpg",
                    "content": "一级评论 A<br/>第二行",
                    "create_time": 1781880000,
                    "like_num": 8,
                    "ip_wording": {"province_name": "北京"},
                    "reply_new": {
                        "reply_total_cnt": 2,
                        "reply_list": [
                            {
                                "reply_id": "r1",
                                "nick_name": "李四",
                                "logo_url": "https://mmbiz.qpic.cn/avatar/reply.jpg",
                                "content": "已有回复",
                                "create_time": 1781880300,
                                "reply_like_num": 3,
                                "multi_info": {
                                    "emojis": [{"url": "https://mmbiz.qpic.cn/emoji/one.gif"}],
                                    "pictures": [{"url": "https://mmbiz.qpic.cn/pic/one.png"}],
                                },
                            }
                        ],
                        "offset": 1,
                        "buffer": "",
                        "max_reply_id": "r1",
                    },
                }
            ],
        }
        second_page = {
            "base_resp": {"ret": 0, "errmsg": "ok"},
            "continue_flag": 0,
            "elected_comment": [
                {
                    "id": "c2",
                    "content_id": "content-2",
                    "nick_name": "王五",
                    "content": "一级评论 B",
                    "create_time": 1781880600,
                    "like_num": 1,
                    "reply_new": {"reply_total_cnt": 0, "reply_list": []},
                }
            ],
        }
        reply_page = {
            "base_resp": {"ret": 0, "errmsg": "ok"},
            "continue_flag": 0,
            "reply_list": {
                "reply_list": [
                    {
                        "reply_id": "r2",
                        "nick_name": "赵六",
                        "content": "补抓回复",
                        "create_time": 1781880900,
                        "reply_like_num": 4,
                    }
                ],
                "max_reply_id": "r2",
            },
            "buffer": "reply-buffer",
        }

        def fake_get(url: str, headers: dict[str, str], timeout_seconds: float):
            requested_urls.append(url)
            requested_headers.append(headers)
            query = parse_qs(urlparse(url).query)
            if query.get("action") == ["getcommentreply"]:
                return FakeResponse(200, reply_page)
            if query.get("offset") == ["0"]:
                return FakeResponse(200, first_page)
            if query.get("offset") == ["1"]:
                self.assertEqual(query.get("buffer"), ["next-buffer"])
                return FakeResponse(200, second_page)
            raise AssertionError(f"unexpected url: {url}")

        def fake_resource_get(url: str, headers: dict[str, str], timeout_seconds: float):
            return FakeBinaryResponse(200, b"image-bytes", {"content-type": "image/png"})

        with tempfile.TemporaryDirectory() as temp_dir:
            article_dir = Path(temp_dir) / "storages" / "测试公众号" / "2026-06-19 21-39 测试文章"
            result = fetch_comments_to_archive(
                keyed_url,
                html_text,
                article_dir,
                request_headers={
                    "User-Agent": "MicroMessenger/8.0",
                    "Cookie": "wxuin=777; pass_ticket=ticket-cookie",
                    "X-Requested-With": "com.tencent.mm",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                },
                collect_time="2026-06-19 22:00:00",
                http_get=fake_get,
                resource_get=fake_resource_get,
                page_pause_seconds=0,
                reply_page_pause_seconds=0,
            )

            final_path = article_dir / "comments_final.json"
            data = json.loads(final_path.read_text(encoding="utf-8"))
            avatar_dir_exists = (final_path.parent / "comments_img" / "avatar").is_dir()
            emoji_dir_exists = (final_path.parent / "comments_img" / "emoji").is_dir()
            other_dir_exists = (final_path.parent / "comments_img" / "other").is_dir()
            resource_file_count = len(list((final_path.parent / "comments_img").glob("*/*")))

        self.assertTrue(result["ok"])
        self.assertEqual(result["comment_count"], 2)
        self.assertEqual(result["reply_count"], 2)
        self.assertEqual(final_path.name, "comments_final.json")
        self.assertEqual(data["schema_version"], "wechat_comments_v1")
        self.assertEqual(data["summary"]["top_level_comment_count"], 2)
        self.assertEqual(data["summary"]["reply_count"], 2)
        self.assertEqual(data["summary"]["reply_missing_count"], 0)
        self.assertEqual(data["comments"][0]["nickname"], "张三")
        self.assertEqual(data["comments"][0]["content"], "一级评论 A\n第二行")
        self.assertEqual(data["comments"][0]["replies"][1]["nickname"], "赵六")
        self.assertIn("raw_payload", data["comments"][0])
        self.assertTrue(avatar_dir_exists)
        self.assertTrue(emoji_dir_exists)
        self.assertTrue(other_dir_exists)
        self.assertGreaterEqual(resource_file_count, 3)
        self.assertIn("action=getcomment", requested_urls[0])
        self.assertIn("action=getcommentreply", requested_urls[2])
        self.assertEqual(requested_headers[0]["referer"], keyed_url)
        self.assertEqual(requested_headers[0]["x-requested-with"], "com.tencent.mm")

    def test_build_comment_page_url_uses_article_runtime_parameters(self) -> None:
        url = build_comment_page_url(
            "https://mp.weixin.qq.com/s?__biz=biz&mid=123&idx=1&sn=sn&key=secret"
            "&pass_ticket=ticket&scene=126&subscene=227&sessionid=sid&enterid=1781882040"
            "&lang=zh_CN&countrycode=CN&ascene=1",
            "<script>var comment_id='comment-id'; var appmsg_token='token'; var ct=1781880000; var comment_scene=0;</script>",
            {"cookie": "wxuin=777"},
            limit=100,
            offset=5,
            buffer="buffer-value",
        )
        query = parse_qs(urlparse(url).query)

        self.assertEqual(urlparse(url).path, "/mp/appmsg_comment")
        self.assertEqual(query["action"], ["getcomment"])
        self.assertEqual(query["__biz"], ["biz"])
        self.assertEqual(query["appmsgid"], ["123"])
        self.assertEqual(query["idx"], ["1"])
        self.assertEqual(query["comment_id"], ["comment-id"])
        self.assertEqual(query["key"], ["secret"])
        self.assertEqual(query["pass_ticket"], ["ticket"])
        self.assertEqual(query["appmsg_token"], ["token"])
        self.assertEqual(query["uin"], ["777"])
        self.assertEqual(query["offset"], ["5"])
        self.assertEqual(query["buffer"], ["buffer-value"])
        self.assertEqual(query["scene"], ["126"])
        self.assertEqual(query["subscene"], ["227"])
        self.assertEqual(query["sessionid"], ["sid"])
        self.assertEqual(query["enterid"], ["1781882040"])
        self.assertEqual(query["send_time"], ["1781880000"])
        self.assertEqual(query["comment_scene"], ["0"])
        self.assertEqual(query["lang"], ["zh_CN"])
        self.assertEqual(query["countrycode"], ["CN"])
        self.assertEqual(query["ascene"], ["1"])

    def test_normalize_comment_request_headers_keeps_wechat_context(self) -> None:
        headers = normalize_comment_request_headers(
            {
                ":method": "GET",
                "Host": "mp.weixin.qq.com",
                "User-Agent": "MicroMessenger/8.0",
                "Cookie": "wxuin=777",
                "Origin": "https://mp.weixin.qq.com",
                "X-Requested-With": "com.tencent.mm",
                "Accept-Encoding": "br",
            },
            referer="https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret",
        )

        self.assertEqual(headers["user-agent"], "MicroMessenger/8.0")
        self.assertEqual(headers["cookie"], "wxuin=777")
        self.assertEqual(headers["origin"], "https://mp.weixin.qq.com")
        self.assertEqual(headers["x-requested-with"], "com.tencent.mm")
        self.assertEqual(headers["accept"], "application/json,text/plain,*/*")
        self.assertEqual(headers["referer"], "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret")
        self.assertNotIn("host", headers)
        self.assertNotIn("accept-encoding", headers)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self.payload = payload
        self.text = json.dumps(payload, ensure_ascii=False)
        self.headers = {"content-type": "application/json; charset=utf-8"}
        self.content = self.text.encode("utf-8")

    def json(self):
        return self.payload


class FakeBinaryResponse:
    def __init__(self, status_code: int, content: bytes, headers: dict[str, str]) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers


if __name__ == "__main__":
    unittest.main()
