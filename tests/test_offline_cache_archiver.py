from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.modules.archive.offline_archiver import CapturedResponseStore
from src.modules.archive.offline_html_rewriter import rewrite_html_resource_links


class _FakeRequest:
    def __init__(self, resource_type: str) -> None:
        self.resource_type = resource_type


class _FakeResponse:
    def __init__(
        self,
        *,
        url: str,
        body: bytes,
        content_type: str,
        resource_type: str,
        status: int = 200,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.url = url
        self.status = status
        self.request = _FakeRequest(resource_type)
        self.headers = {"content-type": content_type, **(extra_headers or {})}
        self._body = body
        self.body_calls = 0

    def body(self) -> bytes:
        self.body_calls += 1
        return self._body


class OfflineCacheArchiverTest(unittest.TestCase):
    def test_response_store_saves_loaded_resource_without_secondary_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            assets_dir = Path(directory) / "assets"
            store = CapturedResponseStore(assets_dir)
            response = _FakeResponse(
                url="https://mmbiz.qpic.cn/article-cover.jpg",
                body=b"image-data",
                content_type="image/jpeg",
                resource_type="image",
            )

            saved = store.capture(response)

            self.assertTrue(saved)
            self.assertEqual(response.body_calls, 1)
            relative_path = store.resource_map[response.url]
            self.assertTrue((Path(directory) / relative_path).is_file())
            self.assertEqual((Path(directory) / relative_path).read_bytes(), b"image-data")

    def test_response_store_skips_partial_video_body(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CapturedResponseStore(Path(directory) / "assets")
            response = _FakeResponse(
                url="https://example.com/video.mp4",
                body=b"partial-video",
                content_type="video/mp4",
                resource_type="media",
                status=206,
                extra_headers={"content-range": "bytes 0-12/1000"},
            )

            saved = store.capture(response)

            self.assertFalse(saved)
            self.assertEqual(response.body_calls, 0)
            self.assertIn("分段媒体", store.warnings[0])

    def test_rewriter_points_rendered_article_resources_to_assets(self) -> None:
        html = (
            '<img data-src="//mmbiz.qpic.cn/a.png">'
            '<video poster="https://mmbiz.qpic.cn/poster.jpg"></video>'
        )
        resource_map = {
            "https://mmbiz.qpic.cn/a.png": "assets/img/a.png",
            "https://mmbiz.qpic.cn/poster.jpg": "assets/img/poster.jpg",
        }

        rewritten = rewrite_html_resource_links(
            html,
            resource_map,
            base_url="https://mp.weixin.qq.com/s/article",
        )

        self.assertIn('data-src="assets/img/a.png"', rewritten)
        self.assertIn('poster="assets/img/poster.jpg"', rewritten)

    def test_saved_css_rewrites_resource_paths_relative_to_css_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            assets_dir = Path(directory) / "assets"
            store = CapturedResponseStore(assets_dir)
            image = _FakeResponse(
                url="https://mmbiz.qpic.cn/background.png",
                body=b"png-data",
                content_type="image/png",
                resource_type="image",
            )
            stylesheet = _FakeResponse(
                url="https://res.wx.qq.com/article.css",
                body=b".cover { background-image: url('https://mmbiz.qpic.cn/background.png'); }",
                content_type="text/css",
                resource_type="stylesheet",
            )

            store.capture(image)
            store.capture(stylesheet)
            store.rewrite_saved_css()

            css_path = Path(directory) / store.resource_map[stylesheet.url]
            css_text = css_path.read_text(encoding="utf-8")
            self.assertIn("url('../img/", css_text)
            self.assertNotIn("url('assets/img/", css_text)


if __name__ == "__main__":
    unittest.main()
