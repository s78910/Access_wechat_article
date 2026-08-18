from __future__ import annotations

import tempfile
import time
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.modules.archive import offline_archiver
from src.modules.archive.offline_archiver import (
    CapturedResponseStore,
    OfflineArchiveRequest,
    _build_playwright_context_options,
    _navigation_target,
    _scroll_page,
)
from src.modules.archive.offline_html_rewriter import rewrite_html_resource_links
from src.modules.archive.offline_media_downloader import MediaDownloadResult


class _FakeRequest:
    def __init__(
        self,
        resource_type: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.resource_type = resource_type
        self.headers = headers or {}


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
        request_headers: dict[str, str] | None = None,
    ) -> None:
        self.url = url
        self.status = status
        self.request = _FakeRequest(resource_type, request_headers)
        self.headers = {"content-type": content_type, **(extra_headers or {})}
        self._body = body
        self.body_calls = 0

    def body(self) -> bytes:
        self.body_calls += 1
        return self._body


class _FakeScrollablePage:
    def __init__(self) -> None:
        self.evaluate_calls = 0
        self.wait_calls = 0
        self.top = 0
        self.height = 3000
        self.viewport = 1000

    def evaluate(self, _script: str) -> dict[str, int]:
        self.evaluate_calls += 1
        self.top = min(self.height - self.viewport, self.top + 800)
        return {"top": self.top, "height": self.height, "viewport": self.viewport}

    def wait_for_timeout(self, _milliseconds: int) -> None:
        self.wait_calls += 1


class _FakeLazyLoadAfterBouncePage:
    def __init__(self) -> None:
        self.evaluate_calls = 0
        self.wait_calls = 0
        self.bounce_calls = 0
        self.top = 2000
        self.height = 3000
        self.viewport = 1000

    def evaluate(self, script: str) -> dict[str, int]:
        self.evaluate_calls += 1
        if "scrollBy(0, -" in script:
            self.bounce_calls += 1
            self.top = max(0, self.top - 350)
            return {"top": self.top, "height": self.height, "viewport": self.viewport}
        if "Math.floor(viewport * 0.9)" in script:
            self.bounce_calls += 1
            self.height = 4200
            self.top = 2600
            return {"top": self.top, "height": self.height, "viewport": self.viewport}
        if "window.scrollBy" in script:
            self.top = min(self.height - self.viewport, self.top + 800)
        return {"top": self.top, "height": self.height, "viewport": self.viewport}

    def wait_for_timeout(self, _milliseconds: int) -> None:
        self.wait_calls += 1


class OfflineCacheArchiverTest(unittest.TestCase):
    def test_stateful_request_builds_playwright_context_options(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            request = OfflineArchiveRequest(
                article_id=1,
                article_title="测试文章",
                article_link="https://mp.weixin.qq.com/s/short",
                stage_dir=Path(directory) / "stage",
                browser_cache_dir=Path(directory) / ".playwright-browsers",
                max_scroll_seconds=30.0,
                resource_timeout_seconds=10.0,
                navigation_url="https://mp.weixin.qq.com/s?__biz=test&key=secret",
                navigation_mode="stateful",
                navigation_user_agent="Wechat UA",
                navigation_headers={"Accept": "text/html", "Referer": "https://mp.weixin.qq.com/"},
                navigation_cookies=({"name": "wxuin", "value": "123", "url": "https://mp.weixin.qq.com/"},),
            )

            options = _build_playwright_context_options(request)

            self.assertEqual(_navigation_target(request), request.navigation_url)
            self.assertEqual(options["user_agent"], "Wechat UA")
            self.assertEqual(options["extra_http_headers"]["Accept"], "text/html")
            self.assertEqual(options["extra_http_headers"]["Referer"], "https://mp.weixin.qq.com/")
            self.assertEqual(options["cookies"][0]["name"], "wxuin")

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

    def test_response_store_registers_partial_video_without_reading_body(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CapturedResponseStore(Path(directory) / "assets")
            response = _FakeResponse(
                url="https://example.com/video.mp4",
                body=b"partial-video",
                content_type="video/mp4",
                resource_type="media",
                status=206,
                extra_headers={"content-range": "bytes 0-12/1000"},
                request_headers={
                    "User-Agent": "Wechat Chromium",
                    "Referer": "https://mp.weixin.qq.com/s/example",
                },
            )

            saved = store.capture(response)

            self.assertFalse(saved)
            self.assertEqual(response.body_calls, 0)
            self.assertEqual(len(store.media_candidates), 1)
            candidate = store.media_candidates[0]
            self.assertEqual(candidate.url, response.url)
            self.assertEqual(candidate.content_type, "video/mp4")
            self.assertEqual(candidate.request_headers["User-Agent"], "Wechat Chromium")
            self.assertEqual(store.warnings, [])

    def test_media_candidate_registration_does_not_block_following_image_capture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            assets_dir = Path(directory) / "assets"
            store = CapturedResponseStore(assets_dir)
            media = _FakeResponse(
                url="https://mpvideo.qpic.cn/video.mp4",
                body=b"video-data",
                content_type="video/mp4",
                resource_type="media",
            )
            image = _FakeResponse(
                url="https://mmbiz.qpic.cn/article-cover.jpg",
                body=b"image-data",
                content_type="image/jpeg",
                resource_type="image",
            )
            media_saved = store.capture(media)
            image_saved = store.capture(image)

            self.assertFalse(media_saved)
            self.assertTrue(image_saved)
            self.assertEqual(media.body_calls, 0)
            self.assertEqual(len(store.media_candidates), 1)
            self.assertIn(image.url, store.resource_map)

    def test_download_registered_media_uses_context_cookies_and_updates_resource_map(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            assets_dir = Path(directory) / "assets"
            media_path = assets_dir / "video" / "saved.mp4"
            media_path.parent.mkdir(parents=True)
            media_path.write_bytes(b"complete-video")
            store = CapturedResponseStore(assets_dir)
            response = _FakeResponse(
                url="https://mpvideo.qpic.cn/video.mp4?auth_key=secret",
                body=b"partial-video",
                content_type="video/mp4",
                resource_type="media",
                status=206,
                extra_headers={"content-range": "bytes 0-12/1000"},
            )
            store.capture(response)
            context = SimpleNamespace(
                cookies=lambda urls: [
                    {"name": "wxuin", "value": "123", "domain": ".qq.com"}
                ]
            )
            received: dict[str, object] = {}

            def fake_download(candidates, assets_dir, *, cookies, timeout_seconds):
                received.update(
                    candidates=tuple(candidates),
                    assets_dir=assets_dir,
                    cookies=tuple(cookies),
                    timeout_seconds=timeout_seconds,
                )
                return (
                    MediaDownloadResult(
                        ok=True,
                        source_url=response.url,
                        content_type="video/mp4",
                        local_path=media_path,
                        relative_path="assets/video/saved.mp4",
                        bytes_downloaded=len(b"complete-video"),
                        message="媒体下载完成",
                    ),
                )

            with patch.object(
                offline_archiver,
                "download_media_candidates",
                side_effect=fake_download,
            ):
                offline_archiver._download_registered_media(
                    store,
                    context=context,
                    timeout_seconds=9.0,
                    started_at=time.monotonic(),
                    on_event=None,
                )

            self.assertEqual(received["assets_dir"], assets_dir)
            self.assertEqual(received["timeout_seconds"], 9.0)
            self.assertEqual(received["cookies"][0]["name"], "wxuin")
            self.assertEqual(store.resource_map[response.url], "assets/video/saved.mp4")

    def test_normalize_lazy_resources_writes_current_media_urls_back_to_dom(self) -> None:
        scripts: list[str] = []
        page = SimpleNamespace(evaluate=lambda script: scripts.append(script))

        offline_archiver._normalize_lazy_loaded_resource_attributes(page)

        self.assertEqual(len(scripts), 1)
        self.assertIn("video, audio", scripts[0])
        self.assertIn("node.currentSrc", scripts[0])
        self.assertIn("node.poster", scripts[0])
        self.assertIn("setAttribute('poster'", scripts[0])

    def test_normalize_lazy_resources_prefers_data_src_for_wechat_image_placeholders(self) -> None:
        scripts: list[str] = []
        page = SimpleNamespace(evaluate=lambda script: scripts.append(script))

        offline_archiver._normalize_lazy_loaded_resource_attributes(page)

        self.assertEqual(len(scripts), 1)
        script = scripts[0]
        self.assertIn("data-before-oversubscription-url", script)
        self.assertIn("isPlaceholderImage", script)
        self.assertIn("node.classList.remove('js_img_placeholder'", script)
        self.assertIn("node.classList.remove('wx_img_placeholder'", script)

    def test_download_explicit_video_posters_uses_playwright_context(self) -> None:
        class _FakeApiResponse:
            ok = True
            status = 200
            headers = {"content-type": "image/jpeg"}

            def body(self) -> bytes:
                return b"poster-data"

        class _FakeRequestContext:
            def __init__(self) -> None:
                self.calls: list[tuple[str, int]] = []

            def get(self, url: str, *, timeout: int):
                self.calls.append((url, timeout))
                return _FakeApiResponse()

        with tempfile.TemporaryDirectory() as directory:
            store = CapturedResponseStore(Path(directory) / "assets")
            request_context = _FakeRequestContext()
            page = SimpleNamespace(
                context=SimpleNamespace(request=request_context),
                evaluate=lambda _script: [
                    "https://mmbiz.qpic.cn/poster.jpg?wx_fmt=jpeg&wxfrom=16"
                ],
            )

            offline_archiver._download_explicit_video_posters(
                page,
                resource_store=store,
                timeout_seconds=8.0,
                started_at=time.monotonic(),
                on_event=None,
            )

            poster_url = "https://mmbiz.qpic.cn/poster.jpg?wx_fmt=jpeg&wxfrom=16"
            self.assertEqual(request_context.calls, [(poster_url, 8000)])
            self.assertIn(poster_url, store.resource_map)
            saved_path = Path(directory) / store.resource_map[poster_url]
            self.assertTrue(saved_path.is_file())
            self.assertEqual(saved_path.read_bytes(), b"poster-data")

    def test_download_explicit_video_posters_reads_wechat_iframe_cover(self) -> None:
        class _FakeApiResponse:
            ok = True
            status = 200
            headers = {"content-type": "image/jpeg"}

            def body(self) -> bytes:
                return b"iframe-poster-data"

        class _FakeRequestContext:
            def __init__(self) -> None:
                self.calls: list[tuple[str, int]] = []

            def get(self, url: str, *, timeout: int):
                self.calls.append((url, timeout))
                return _FakeApiResponse()

        encoded_cover = (
            "http%3A%2F%2Fmmbiz.qpic.cn%2Fsz_mmbiz_jpg%2Fposter%2F0"
            "%3Fwx_fmt%3Djpeg"
        )
        decoded_cover = "http://mmbiz.qpic.cn/sz_mmbiz_jpg/poster/0?wx_fmt=jpeg"

        with tempfile.TemporaryDirectory() as directory:
            store = CapturedResponseStore(Path(directory) / "assets")
            request_context = _FakeRequestContext()
            page = SimpleNamespace(
                context=SimpleNamespace(request=request_context),
                evaluate=lambda _script: [encoded_cover],
            )

            offline_archiver._download_explicit_video_posters(
                page,
                resource_store=store,
                timeout_seconds=8.0,
                started_at=time.monotonic(),
                on_event=None,
            )

            self.assertEqual(request_context.calls, [(decoded_cover, 8000)])
            self.assertIn(decoded_cover, store.resource_map)
            saved_path = Path(directory) / store.resource_map[decoded_cover]
            self.assertEqual(saved_path.read_bytes(), b"iframe-poster-data")

    def test_register_embedded_media_candidates_extracts_wechat_script_video_url(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CapturedResponseStore(Path(directory) / "assets")
            html = (
                "url: 'http://mpvideo.qpic.cn/video.f10002.mp4?"
                "dis_k=abc\\x26amp;dis_t=123\\x26amp;auth_key=secret',"
                "url: 'http://mpvideo.qpic.cn/video.f10004.mp4?"
                "dis_k=def\\x26amp;dis_t=123\\x26amp;auth_key=secret2',"
            )

            offline_archiver._register_embedded_media_candidates_from_html(
                html,
                store,
                request_headers={"User-Agent": "Wechat UA"},
                started_at=time.monotonic(),
                on_event=None,
            )

            self.assertEqual(len(store.media_candidates), 1)
            candidate = store.media_candidates[0]
            self.assertEqual(
                candidate.url,
                "http://mpvideo.qpic.cn/video.f10002.mp4?"
                "dis_k=abc&dis_t=123&auth_key=secret",
            )
            self.assertEqual(candidate.content_type, "video/mp4")
            self.assertEqual(candidate.request_headers["User-Agent"], "Wechat UA")

    def test_download_wechat_videosnap_assets_saves_static_cover_without_video_candidate(self) -> None:
        class _FakeApiResponse:
            ok = True
            status = 200
            headers = {"content-type": "image/png"}

            def body(self) -> bytes:
                return b"image-data"

        class _FakeRequestContext:
            def __init__(self) -> None:
                self.calls: list[tuple[str, int]] = []

            def get(self, url: str, *, timeout: int):
                self.calls.append((url, timeout))
                return _FakeApiResponse()

        cover_url = "https://findermp.video.qq.com/251/20304/stodownload?token=secret&picformat=200"
        headimg_url = "https://wx.qlogo.cn/finderhead/avatar/0"
        authicon_url = "http://dldir1.qq.com/weixin/checkresupdate/auth.png"

        with tempfile.TemporaryDirectory() as directory:
            store = CapturedResponseStore(Path(directory) / "assets")
            request_context = _FakeRequestContext()

            def fake_evaluate(script: str):
                if "mp-common-videosnap" in script:
                    return [
                        {
                            "coverUrls": [cover_url],
                            "imageUrls": [headimg_url, authicon_url],
                        }
                    ]
                return ""

            page = SimpleNamespace(
                url="https://mp.weixin.qq.com/s/article",
                context=SimpleNamespace(request=request_context),
                evaluate=fake_evaluate,
            )

            offline_archiver._download_wechat_videosnap_assets(
                page,
                resource_store=store,
                timeout_seconds=8.0,
                started_at=time.monotonic(),
                on_event=None,
            )

            self.assertEqual(
                request_context.calls,
                [(cover_url, 8000), (headimg_url, 8000), (authicon_url, 8000)],
            )
            self.assertEqual(store.media_candidates, [])
            self.assertIn(cover_url, store.resource_map)
            self.assertIn(headimg_url, store.resource_map)
            self.assertIn(authicon_url, store.resource_map)

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

    def test_rewriter_matches_html_escaped_authenticated_media_url(self) -> None:
        source_url = "https://mpvideo.qpic.cn/video.mp4?auth_key=secret&dis_t=123"
        html = (
            '<video src="https://mpvideo.qpic.cn/video.mp4?'
            'auth_key=secret&amp;dis_t=123"></video>'
        )

        rewritten = rewrite_html_resource_links(
            html,
            {source_url: "assets/video/saved.mp4"},
            base_url="https://mp.weixin.qq.com/s/article",
        )

        self.assertIn('src="assets/video/saved.mp4"', rewritten)
        self.assertNotIn("auth_key", rewritten)

    def test_rewriter_matches_wechat_image_url_with_fragment(self) -> None:
        source_url = "https://mmbiz.qpic.cn/mmbiz/example/640?wx_fmt=gif"
        html = (
            '<img src="https://mmbiz.qpic.cn/mmbiz/example/640?'
            'wx_fmt=gif#imgIndex=5" '
            'data-src="https://mmbiz.qpic.cn/mmbiz/example/640?'
            'wx_fmt=gif&amp;wxfrom=5#imgIndex=5">'
        )

        rewritten = rewrite_html_resource_links(
            html,
            {source_url: "assets/img/example.gif"},
            base_url="https://mp.weixin.qq.com/s/article",
        )

        self.assertIn('src="assets/img/example.gif"', rewritten)
        self.assertIn('data-src="assets/img/example.gif"', rewritten)
        self.assertNotIn("mmbiz.qpic.cn", rewritten)

    def test_rewriter_enables_native_media_controls_and_hides_wechat_overlay(self) -> None:
        html = """
        <div class="js_video_poster video_poster">
          <div class="video_mask"></div>
          <i class="pic_mid_play"></i>
          <div class="poster_cover"></div>
          <video src="https://mpvideo.qpic.cn/video.mp4?token=secret"
                 crossorigin="anonymous"
                 controlslist="nodownload"></video>
        </div>
        <div class="full_screen_opr wx_video_play_opr">
          <span class="video_length">00:38</span>
        </div>
        <div class="video_poster__info__play"></div>
        <audio src="https://res.wx.qq.com/audio.m4a"></audio>
        """

        rewritten = rewrite_html_resource_links(
            html,
            {
                "https://mpvideo.qpic.cn/video.mp4?token=secret": "assets/video/saved.mp4",
                "https://res.wx.qq.com/audio.m4a": "assets/audio/saved.m4a",
            },
            base_url="https://mp.weixin.qq.com/s/article",
        )

        self.assertIn('src="assets/video/saved.mp4"', rewritten)
        self.assertIn('src="assets/audio/saved.m4a"', rewritten)
        self.assertRegex(rewritten, r"<video\b[^>]*\bcontrols\b")
        self.assertRegex(rewritten, r"<audio\b[^>]*\bcontrols\b")
        self.assertNotIn("crossorigin", rewritten.lower())
        self.assertRegex(rewritten, r'class="video_mask"[^>]*style="[^"]*display:\s*none')
        self.assertRegex(rewritten, r'class="pic_mid_play"[^>]*style="[^"]*display:\s*none')
        self.assertRegex(
            rewritten,
            r'class="video_poster__info__play"[^>]*style="[^"]*display:\s*none',
        )
        self.assertRegex(rewritten, r'class="full_screen_opr wx_video_play_opr"[^>]*style="[^"]*display:\s*none')
        self.assertRegex(rewritten, r'class="video_length"[^>]*style="[^"]*display:\s*none')
        self.assertRegex(rewritten, r'class="poster_cover"[^>]*style="[^"]*display:\s*none')
        self.assertIn('data-awa-offline-media-toggle="1"', rewritten)
        self.assertIn("media.play()", rewritten)

    def test_rewriter_replaces_video_poster_with_local_asset(self) -> None:
        poster_url = "http://mmbiz.qpic.cn/sz_mmbiz_jpg/poster/0?wx_fmt=jpeg&wxfrom=16"
        html = f'<body><video poster="{poster_url}"></video></body>'

        rewritten = rewrite_html_resource_links(
            html,
            {poster_url: "assets/img/poster.jpg"},
            base_url="https://mp.weixin.qq.com/s/article",
        )

        self.assertIn('poster="assets/img/poster.jpg"', rewritten)
        self.assertNotIn("mmbiz.qpic.cn", rewritten)

    def test_rewriter_normalizes_video_to_source_markup(self) -> None:
        html = (
            '<body><video src="https://mpvideo.qpic.cn/video.mp4?token=secret" '
            'poster="https://mmbiz.qpic.cn/poster.jpg" '
            'controlslist="nodownload" playsinline="isiPhoneShowPlaysinline" '
            'webkit-playsinline="isiPhoneShowPlaysinline"></video></body>'
        )

        rewritten = rewrite_html_resource_links(
            html,
            {
                "https://mpvideo.qpic.cn/video.mp4?token=secret": "assets/video/saved.mp4",
                "https://mmbiz.qpic.cn/poster.jpg": "assets/img/poster.jpg",
            },
            base_url="https://mp.weixin.qq.com/s/article",
        )

        video_open = re.search(r"<video\b[^>]*>", rewritten).group(0)
        self.assertIn("<video", video_open)
        self.assertIn("controls", video_open)
        self.assertIn('poster="assets/img/poster.jpg"', video_open)
        self.assertNotIn(" src=", video_open)
        self.assertNotIn("controlslist", rewritten)
        self.assertNotIn("playsinline", rewritten.lower())
        self.assertIn('<source src="assets/video/saved.mp4" type="video/mp4">', rewritten)
        self.assertIn('href="assets/video/saved.mp4"', rewritten)
        self.assertIn("当前浏览器不支持 HTML5 视频", rewritten)

    def test_rewriter_converts_wechat_video_iframe_to_native_video_when_media_saved(self) -> None:
        cover_url = "http://mmbiz.qpic.cn/sz_mmbiz_jpg/poster/0?wx_fmt=jpeg"
        encoded_cover = "http%3A%2F%2Fmmbiz.qpic.cn%2Fsz_mmbiz_jpg%2Fposter%2F0%3Fwx_fmt%3Djpeg"
        media_url = "http://mpvideo.qpic.cn/video.f10002.mp4?auth_key=secret"
        html = (
            '<section><iframe class="video_iframe rich_pages" '
            'data-src="https://mp.weixin.qq.com/mp/readtemplate?t=pages/video_player_tmpl&amp;auto=0&amp;vid=wxv_1" '
            'data-mpvid="wxv_1" data-cover="'
            f'{encoded_cover}" data-ratio="0.5625" data-w="1080" '
            'style="display: none;"></iframe>'
            '<span class="js_img_placeholder wx_widget_placeholder" data-vid="wxv_1">'
            '<span class="weui-primary-loading"></span></span></section>'
        )

        rewritten = rewrite_html_resource_links(
            html,
            {
                cover_url: "assets/img/video-cover.jpg",
                media_url: "assets/video/saved.mp4",
            },
            base_url="https://mp.weixin.qq.com/s/article",
        )

        self.assertNotIn("<iframe", rewritten)
        self.assertIn("<video", rewritten)
        self.assertIn('poster="assets/img/video-cover.jpg"', rewritten)
        self.assertIn('<source src="assets/video/saved.mp4" type="video/mp4">', rewritten)
        self.assertRegex(
            rewritten,
            r'class="js_img_placeholder wx_widget_placeholder"[^>]*style="[^"]*display:\s*none',
        )

    def test_rewriter_converts_wechat_video_iframe_to_static_cover_when_media_missing(self) -> None:
        cover_url = "http://mmbiz.qpic.cn/sz_mmbiz_jpg/poster/0?wx_fmt=jpeg"
        encoded_cover = "http%3A%2F%2Fmmbiz.qpic.cn%2Fsz_mmbiz_jpg%2Fposter%2F0%3Fwx_fmt%3Djpeg"
        html = (
            '<iframe class="video_iframe rich_pages" data-mpvid="wxv_1" '
            f'data-cover="{encoded_cover}" data-ratio="0.5625" style="display: none;"></iframe>'
        )

        rewritten = rewrite_html_resource_links(
            html,
            {cover_url: "assets/img/video-cover.jpg"},
            base_url="https://mp.weixin.qq.com/s/article",
        )

        self.assertNotIn("<iframe", rewritten)
        self.assertNotIn("<video", rewritten)
        self.assertIn('class="awa-offline-video-placeholder"', rewritten)
        self.assertIn('src="assets/img/video-cover.jpg"', rewritten)

    def test_rewriter_converts_wechat_videosnap_to_static_cover(self) -> None:
        cover_url = "https://findermp.video.qq.com/251/20304/stodownload?token=secret&picformat=200"
        headimg_url = "https://wx.qlogo.cn/finderhead/avatar/0"
        html = (
            '<mp-common-videosnap data-pluginname="mpvideosnap" '
            f'data-url="{cover_url}" data-headimgurl="{headimg_url}" '
            'data-nickname="人民日报" data-desc="少年网恋后欲独自赴泰国" '
            'data-width="1080" data-height="1440" data-type="video" '
            'style="visibility: visible;"></mp-common-videosnap>'
        )

        rewritten = rewrite_html_resource_links(
            html,
            {
                cover_url: "assets/img/finder-cover.png",
                headimg_url: "assets/img/avatar.png",
            },
            base_url="https://mp.weixin.qq.com/s/article",
        )

        self.assertNotIn("mp-common-videosnap", rewritten)
        self.assertIn('class="awa-offline-videosnap"', rewritten)
        self.assertIn('class="wxw_wechannel_video_context"', rewritten)
        self.assertIn("background-image:url('assets/img/finder-cover.png')", rewritten)
        self.assertIn('class="weui-play-btn_primary"', rewritten)
        self.assertNotIn("<video", rewritten)
        self.assertNotIn("assets/video", rewritten)

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

    def test_rewriter_sanitizes_networking_html_and_preserves_read_original_href(self) -> None:
        html = """
        <html>
          <head>
            <link rel="preconnect" href="https://res.wx.qq.com">
            <link rel="dns-prefetch" href="//mmbiz.qpic.cn">
            <link rel="preload" href="https://res.wx.qq.com/a.css" as="style">
            <style>
              .cover { background-image: url('https://mmbiz.qpic.cn/bg.png'); }
            </style>
            <script src="https://res.wx.qq.com/network.js"></script>
          </head>
          <body onload="boot()">
            <noscript>enable js</noscript>
            <img src="https://mmbiz.qpic.cn/a.png" onerror="retry()">
            <a id="js_view_source" href="https://mp.weixin.qq.com/s/original" onclick="track()">阅读原文</a>
          </body>
        </html>
        """
        resource_map = {
            "https://mmbiz.qpic.cn/a.png": "assets/img/a.png",
            "https://mmbiz.qpic.cn/bg.png": "assets/img/bg.png",
        }

        rewritten = rewrite_html_resource_links(
            html,
            resource_map,
            base_url="https://mp.weixin.qq.com/s/article",
        )

        self.assertNotIn("<script", rewritten.lower())
        self.assertNotIn("<noscript", rewritten.lower())
        self.assertNotIn(" onload=", rewritten.lower())
        self.assertNotIn(" onerror=", rewritten.lower())
        self.assertNotIn(" onclick=", rewritten.lower())
        self.assertNotIn('rel="preconnect"', rewritten.lower())
        self.assertNotIn('rel="dns-prefetch"', rewritten.lower())
        self.assertNotIn('rel="preload"', rewritten.lower())
        self.assertIn('src="assets/img/a.png"', rewritten)
        self.assertIn("url('assets/img/bg.png')", rewritten)
        self.assertIn('href="https://mp.weixin.qq.com/s/original"', rewritten)

    def test_prepare_offline_document_keeps_wechat_original_page_structure(self) -> None:
        from src.modules.archive import offline_archiver

        html = """
        <!doctype html>
        <html>
          <head><title>微信文章原页</title></head>
          <body>
            <div id="page-content" class="rich_media">
              <h1 id="activity-name">原始标题</h1>
              <div id="js_content" class="rich_media_content">
                <p>正文</p>
                <img data-src="https://mmbiz.qpic.cn/a.png">
              </div>
              <div class="rich_media_tool">
                <a id="js_view_source" href="https://mp.weixin.qq.com/s/original">阅读原文</a>
              </div>
            </div>
          </body>
        </html>
        """

        prepared = offline_archiver._prepare_offline_document_html(
            html,
            resource_map={"https://mmbiz.qpic.cn/a.png": "assets/img/a.png"},
            base_url="https://mp.weixin.qq.com/s/article",
        )

        self.assertIn('id="page-content"', prepared)
        self.assertIn('class="rich_media"', prepared)
        self.assertIn('id="js_content"', prepared)
        self.assertIn('data-src="assets/img/a.png"', prepared)
        self.assertIn('href="https://mp.weixin.qq.com/s/original"', prepared)
        self.assertIn('target="_blank"', prepared)
        self.assertIn('rel="noopener noreferrer"', prepared)
        self.assertNotIn("<article>", prepared)

    def test_prepare_offline_document_restores_read_original_link_from_page_data(self) -> None:
        html = """
        <!doctype html>
        <html>
          <body>
            <script>
              var msg_source_url = 'https://www.peopleapp.com/home?from=wechat\\x26scene=1';
            </script>
            <div class="rich_media_tool">
              <a role="button" tabindex="0"
                 class="media_tool_meta meta_primary js_wx_tap_highlight wx_tap_link">
                阅读原文
              </a>
            </div>
          </body>
        </html>
        """

        prepared = offline_archiver._prepare_offline_document_html(
            html,
            resource_map={},
            base_url="https://mp.weixin.qq.com/s/article",
        )

        self.assertNotIn("<script", prepared.lower())
        self.assertIn(
            'href="https://www.peopleapp.com/home?from=wechat&amp;scene=1"',
            prepared,
        )
        self.assertIn('target="_blank"', prepared)
        self.assertIn('rel="noopener noreferrer"', prepared)

    def test_scroll_page_continues_until_stable_bottom_without_fixed_count_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CapturedResponseStore(Path(directory) / "assets")
            page = _FakeScrollablePage()
            events: list[dict[str, object]] = []

            _scroll_page(
                page,
                resource_store=store,
                max_scroll_seconds=5.0,
                started_at=time.monotonic(),
                on_event=events.append,
            )

            event_names = [str(event["name"]) for event in events]
            self.assertGreater(page.evaluate_calls, 1)
            self.assertIn("页面滚动 第 1 次", event_names)
            self.assertFalse(any("/1" in name for name in event_names))
            self.assertNotIn("已达到最大滚动次数", store.warnings)

    def test_scroll_page_bounces_and_rechecks_when_bottom_does_not_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CapturedResponseStore(Path(directory) / "assets")
            page = _FakeLazyLoadAfterBouncePage()
            events: list[dict[str, object]] = []

            _scroll_page(
                page,
                resource_store=store,
                max_scroll_seconds=5.0,
                started_at=time.monotonic(),
                on_event=events.append,
            )

            event_names = [str(event["name"]) for event in events]
            self.assertGreaterEqual(page.bounce_calls, 2)
            self.assertIn("页面无变化，执行回弹滚动", event_names)
            self.assertIn("回弹后检测到新内容", event_names)


if __name__ == "__main__":
    unittest.main()
