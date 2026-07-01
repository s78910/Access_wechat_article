from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.modules.html_archive.html_rewriter import (
    bind_read_original_link_in_html,
    extract_resource_urls_from_css,
    extract_resource_urls_from_html,
    rewrite_css_urls,
    rewrite_html_resource_links,
)
from src.modules.html_archive.article_html_archiver import (
    build_article_only_html,
    build_chromium_launch_kwargs,
    build_unavailable_article_html,
    build_scroll_warning,
    clean_article_content_html,
    ensure_playwright_browser_path,
    is_unavailable_article_snapshot,
    prepare_archive_output_dirs,
    select_missing_resource_urls,
    should_save_article_resource,
)
from src.modules.html_archive.models import ArticleHtmlArchiveConfig, ArticleHtmlArchiveTask
from src.modules.html_archive.resource_store import save_asset
from src.modules.html_archive.scroll_strategy import AdaptiveScrollController, ScrollSnapshot
from src.modules.html_archive.sqlite_task_reader import load_saved_article_html_archive_tasks
from src.modules.html_archive.url_guard import normalize_plain_wechat_short_link
from src.modules.storage.sqlite_store import SQLiteStore
from src.workers.article_html_archive_worker import run_html_archive_tasks


class HtmlArchiveModuleTest(unittest.TestCase):
    def test_plain_short_link_rejects_keyed_or_query_urls(self) -> None:
        self.assertEqual(
            normalize_plain_wechat_short_link("https://mp.weixin.qq.com/s/testShort123"),
            "https://mp.weixin.qq.com/s/testShort123",
        )
        self.assertEqual(
            normalize_plain_wechat_short_link("https://mp.weixin.qq.com/s/testShort123/"),
            "https://mp.weixin.qq.com/s/testShort123",
        )
        self.assertEqual(
            normalize_plain_wechat_short_link("https://mp.weixin.qq.com/s/testShort123?key=secret"),
            "",
        )
        self.assertEqual(
            normalize_plain_wechat_short_link("https://mp.weixin.qq.com/s?__biz=abc&key=secret"),
            "",
        )
        self.assertEqual(normalize_plain_wechat_short_link("http://mp.weixin.qq.com/s/testShort123"), "")

    def test_sqlite_loader_returns_latest_saved_short_link_task_from_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "awa_public.sqlite3"
            storage_root = root / "storages"
            store = SQLiteStore(db_path)
            store.save_public_article(
                {
                    "account_name": "测试公众号",
                    "article_title": "有效文章",
                    "published_article_time": "2026-06-20 10:30",
                    "article_link": "https://mp.weixin.qq.com/s/valid-short",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-20 10:31:00",
                    "collect_status": "saved",
                }
            )
            store.save_public_article(
                {
                    "account_name": "测试公众号",
                    "article_title": "失败文章",
                    "published_article_time": "",
                    "article_link": "",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-20 10:32:00",
                    "collect_status": "failed",
                }
            )
            store.save_public_article(
                {
                    "account_name": "测试公众号",
                    "article_title": "带参数文章",
                    "published_article_time": "2026-06-20 11:30",
                    "article_link": "https://mp.weixin.qq.com/s/keyed-short?key=secret",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-20 11:31:00",
                    "collect_status": "saved",
                }
            )

            tasks = load_saved_article_html_archive_tasks(db_path, storage_root=storage_root, limit=1)

            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].short_link, "https://mp.weixin.qq.com/s/valid-short")
            self.assertEqual(tasks[0].account_name, "测试公众号")
            self.assertEqual(tasks[0].article_title, "有效文章")
            self.assertEqual(tasks[0].published_article_time, "2026-06-20 10:30")
            self.assertEqual(tasks[0].storage_root, storage_root)

    def test_resource_store_uses_assets_subdirectories_and_safe_hashed_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            assets_dir = Path(temp_dir) / "assets"

            saved = save_asset(
                assets_dir,
                url="https://res.wx.qq.com/image/test?id=1&name=a/b.png",
                data=b"image-bytes",
                content_type="image/png",
            )
            saved_again = save_asset(
                assets_dir,
                url="https://res.wx.qq.com/image/test?id=1&name=a/b.png",
                data=b"image-bytes",
                content_type="image/png",
            )

            self.assertTrue(saved.local_path.is_file())
            self.assertEqual(saved.local_path, saved_again.local_path)
            self.assertEqual(saved.kind, "img")
            self.assertEqual(saved.relative_path, saved_again.relative_path)
            self.assertTrue(saved.relative_path.startswith("assets/img/"))
            self.assertTrue(saved.relative_path.endswith(".png"))

    def test_article_resource_filter_keeps_media_and_skips_page_shell_assets(self) -> None:
        self.assertTrue(should_save_article_resource("https://mmbiz.qpic.cn/a.jpg", "image/jpeg"))
        self.assertTrue(should_save_article_resource("https://example.com/movie.mp4", "video/mp4"))
        self.assertFalse(should_save_article_resource("https://res.wx.qq.com/app.js", "application/javascript"))
        self.assertFalse(should_save_article_resource("https://res.wx.qq.com/app.css", "text/css"))
        self.assertFalse(should_save_article_resource("https://res.wx.qq.com/font.woff2", "font/woff2"))
        self.assertFalse(should_save_article_resource("https://example.com/unknown.bin", "application/octet-stream"))

    def test_html_and_css_rewriter_localizes_known_assets(self) -> None:
        html_doc = """
        <html>
          <head><link rel="stylesheet" href="/style/app.css"></head>
          <body>
            <img src="https://res.wx.qq.com/a.jpg">
            <img data-src="//res.wx.qq.com/b.png">
            <source srcset="https://res.wx.qq.com/one.jpg 1x, https://res.wx.qq.com/two.jpg 2x">
            <div style="background-image: url('/img/bg.png')"></div>
          </body>
        </html>
        """
        resource_map = {
            "https://mp.weixin.qq.com/style/app.css": "assets/css/app.css",
            "https://res.wx.qq.com/a.jpg": "assets/img/a.jpg",
            "https://res.wx.qq.com/b.png": "assets/img/b.png",
            "https://res.wx.qq.com/one.jpg": "assets/img/one.jpg",
            "https://res.wx.qq.com/two.jpg": "assets/img/two.jpg",
            "https://mp.weixin.qq.com/img/bg.png": "assets/img/bg.png",
            "https://res.wx.qq.com/font.woff2": "assets/font/font.woff2",
        }

        rewritten_html = rewrite_html_resource_links(
            html_doc,
            resource_map,
            base_url="https://mp.weixin.qq.com/s/testShort123",
        )
        rewritten_css = rewrite_css_urls(
            "body{background:url('/img/bg.png')} @font-face{src:url(\"https://res.wx.qq.com/font.woff2\")}",
            resource_map,
            base_url="https://mp.weixin.qq.com/style/app.css",
        )

        self.assertIn('href="assets/css/app.css"', rewritten_html)
        self.assertIn('src="assets/img/a.jpg"', rewritten_html)
        self.assertIn('data-src="assets/img/b.png"', rewritten_html)
        self.assertIn('srcset="assets/img/one.jpg 1x, assets/img/two.jpg 2x"', rewritten_html)
        self.assertIn("url('assets/img/bg.png')", rewritten_html)
        self.assertIn("url('assets/img/bg.png')", rewritten_css)
        self.assertIn("url('assets/font/font.woff2')", rewritten_css)

    def test_css_resource_extractor_skips_svg_fragment_and_domain_roots(self) -> None:
        urls = extract_resource_urls_from_css(
            """
            .icon{clip-path:url(#clip0)}
            .encoded{clip-path:url('assets/%23clip0_107_24357')}
            .root{background:url('https://res.wx.qq.com')}
            .cdn{background:url('//mmbiz.qpic.cn')}
            .ok{background:url('/mmbiz_png/a.png')}
            """,
            base_url="https://mp.weixin.qq.com/s/testShort123",
        )

        self.assertEqual(urls, ["https://mp.weixin.qq.com/mmbiz_png/a.png"])

    def test_html_resource_extractor_only_reads_actual_article_media_resources(self) -> None:
        article_html = """
        <section id="js_content">
          <script src="https://res.wx.qq.com/no-need.js"></script>
          <a href="https://www.peopleapp.com/">阅读原文</a>
          <img src="https://mmbiz.qpic.cn/article-cover.jpg">
          <img data-src="//mmbiz.qpic.cn/article-lazy.png">
          <video poster="/poster.jpg"><source src="/movie.mp4"></video>
          <span style="background-image: url('/inline-bg.png')"></span>
        </section>
        """

        urls = extract_resource_urls_from_html(article_html, base_url="https://mp.weixin.qq.com/s/testShort123")

        self.assertEqual(
            urls,
            [
                "https://mmbiz.qpic.cn/article-cover.jpg",
                "https://mmbiz.qpic.cn/article-lazy.png",
                "https://mp.weixin.qq.com/poster.jpg",
                "https://mp.weixin.qq.com/movie.mp4",
                "https://mp.weixin.qq.com/inline-bg.png",
            ],
        )

    def test_read_original_text_is_bound_to_source_url(self) -> None:
        html_doc = '<div class="rich_media_tool"><span id="js_view_source">阅读原文</span></div>'

        rewritten = bind_read_original_link_in_html(html_doc, "https://www.peopleapp.com/")

        self.assertIn('href="https://www.peopleapp.com/"', rewritten)
        self.assertIn("阅读原文", rewritten)
        self.assertIn('target="_blank"', rewritten)

    def test_runtime_forces_project_playwright_browser_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            old_value = __import__("os").environ.get("PLAYWRIGHT_BROWSERS_PATH")
            try:
                __import__("os").environ["PLAYWRIGHT_BROWSERS_PATH"] = "D:/some/global/cache"
                target = Path(temp_dir) / ".playwright-browsers"
                resolved = ensure_playwright_browser_path(ArticleHtmlArchiveConfig(browser_cache_dir=target))

                self.assertEqual(resolved, target)
                self.assertEqual(__import__("os").environ["PLAYWRIGHT_BROWSERS_PATH"], str(target))
            finally:
                if old_value is None:
                    __import__("os").environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
                else:
                    __import__("os").environ["PLAYWRIGHT_BROWSERS_PATH"] = old_value

    def test_playwright_launch_defaults_to_direct_network(self) -> None:
        launch_kwargs = build_chromium_launch_kwargs(ArticleHtmlArchiveConfig(headless=True))

        self.assertTrue(launch_kwargs["headless"])
        self.assertIn("--proxy-server=direct://", launch_kwargs["args"])
        self.assertIn("--proxy-bypass-list=*", launch_kwargs["args"])

    def test_playwright_launch_can_preserve_extra_chromium_args(self) -> None:
        launch_kwargs = build_chromium_launch_kwargs(
            ArticleHtmlArchiveConfig(chromium_launch_args=("--disable-gpu",))
        )

        self.assertIn("--disable-gpu", launch_kwargs["args"])
        self.assertIn("--proxy-server=direct://", launch_kwargs["args"])

    def test_playwright_launch_can_disable_direct_network_override(self) -> None:
        launch_kwargs = build_chromium_launch_kwargs(
            ArticleHtmlArchiveConfig(bypass_system_proxy=False, chromium_launch_args=("--disable-gpu",))
        )

        self.assertEqual(launch_kwargs["args"], ["--disable-gpu"])

    def test_prepare_archive_output_dirs_removes_stale_assets_before_resaving(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_dir = Path(temp_dir) / "archive"
            assets_dir = archive_dir / "assets"
            stale_file = assets_dir / "js" / "old.js"
            stale_file.parent.mkdir(parents=True)
            stale_file.write_text("old", encoding="utf-8")

            prepare_archive_output_dirs(archive_dir, assets_dir)

            self.assertTrue(archive_dir.is_dir())
            self.assertTrue(assets_dir.is_dir())
            self.assertFalse(stale_file.exists())

    def test_verify_page_snapshot_saves_clean_unavailable_html_without_page_shell(self) -> None:
        reason = is_unavailable_article_snapshot(
            {
                "hasArticleContent": False,
                "isVerifyPage": True,
                "content": "<script src='//res.wx.qq.com/app.js'></script>",
            }
        )

        html_doc = build_unavailable_article_html(
            title="黑马！佛得角出线了！",
            reason=reason,
            source_url="https://mp.weixin.qq.com/s/testShort123",
        )

        self.assertIn("未获取到文章正文", html_doc)
        self.assertIn('href="https://mp.weixin.qq.com/s/testShort123"', html_doc)
        self.assertNotIn("<script", html_doc.lower())
        self.assertNotIn("<link", html_doc.lower())
        self.assertNotIn("res.wx.qq.com", html_doc.lower())

    def test_article_content_cleaner_removes_empty_heading_blocks_but_keeps_real_content(self) -> None:
        raw_content = """
        <p><span>蓝色导语</span></p>
        <h1 data-pm-slice="0 0 []"><span><span><br></span></span></h1>
        <h2><span>&nbsp;</span></h2>
        <p style="text-indent:2em"><span><br></span></p>
        <section><img src="https://mmbiz.qpic.cn/a.jpg"></section>
        <p><span>保留<br>正文换行</span></p>
        <p style="text-indent:2em"><span>正文段落</span></p>
        """

        cleaned = clean_article_content_html(raw_content)

        self.assertNotIn("<h1", cleaned.lower())
        self.assertNotIn("<h2", cleaned.lower())
        self.assertIn("蓝色导语", cleaned)
        self.assertIn("<br", cleaned.lower())
        self.assertIn("<img", cleaned.lower())
        self.assertIn("正文段落", cleaned)

    def test_article_only_template_uses_wechat_like_shell_styles(self) -> None:
        html_doc = build_article_only_html(
            title='<span class="js_title_inner">标题</span>',
            meta="""
            <span class="rich_media_meta rich_media_meta_nickname" id="profileBt">
              <a href="javascript:void(0);" id="js_name">人民日报</a>
              <div id="js_profile_card"></div>
            </span>
            <span id="meta_content_hide_info">
              <em id="publish_time" class="rich_media_meta rich_media_meta_text">2026年6月27日 09:09</em>
              <em id="js_ip_wording_wrp" class="rich_media_meta rich_media_meta_text">北京</em>
            </span>
            """,
            content='<h1><span><br></span></h1><p style="text-indent:2em"><span>正文</span></p>',
            tool='<a href="https://www.peopleapp.com/home">阅读原文</a>',
        )

        self.assertIn('class="article-page rich_media_area_primary_inner"', html_doc)
        self.assertIn('class="article-title rich_media_title"', html_doc)
        self.assertIn('id="js_content" class="article-content rich_media_content"', html_doc)
        self.assertIn("width: min(677px, calc(100vw - 32px))", html_doc)
        self.assertIn("padding: 20px 0 48px", html_doc)
        self.assertIn("#js_profile_card", html_doc)
        self.assertIn("display: none !important", html_doc)
        self.assertIn(".article-meta a", html_doc)
        self.assertIn("text-decoration: none", html_doc)
        self.assertIn(".article-meta em", html_doc)
        self.assertIn("font-style: normal", html_doc)
        self.assertIn(".article-content p", html_doc)
        self.assertIn("margin: 0", html_doc)
        self.assertNotIn("\n    h1 {", html_doc)
        self.assertNotIn("<h1><span><br></span></h1>", html_doc)

    def test_scroll_controller_stops_short_page_quickly_and_continues_long_page(self) -> None:
        config = ArticleHtmlArchiveConfig(
            scroll_step_ratio=0.8,
            stable_rounds=3,
            short_page_stable_rounds=1,
            max_scrolls=300,
            max_scroll_seconds=90,
        )

        short_controller = AdaptiveScrollController(config)
        short_decision = short_controller.evaluate(
            ScrollSnapshot(
                scroll_top=0,
                viewport_height=1000,
                scroll_height=900,
                target_bottom=850,
                image_count=2,
                pending_lazy_count=0,
                resource_count=2,
                elapsed_seconds=0.1,
                scroll_count=0,
            )
        )
        self.assertTrue(short_decision.stop)
        self.assertEqual(short_decision.reason, "short_page_loaded")

        long_controller = AdaptiveScrollController(config)
        first_long_decision = long_controller.evaluate(
            ScrollSnapshot(
                scroll_top=0,
                viewport_height=1000,
                scroll_height=50000,
                target_bottom=48000,
                image_count=50,
                pending_lazy_count=30,
                resource_count=50,
                elapsed_seconds=1,
                scroll_count=1,
            )
        )
        self.assertFalse(first_long_decision.stop)
        self.assertEqual(long_controller.next_scroll_distance(first_long_decision.snapshot), 800)

        stable_snapshots = [
            ScrollSnapshot(47200, 1000, 50000, 48000, 120, 0, 140, 20, 280),
            ScrollSnapshot(47200, 1000, 50000, 48000, 120, 0, 140, 21, 281),
            ScrollSnapshot(47200, 1000, 50000, 48000, 120, 0, 140, 22, 282),
        ]
        decisions = [long_controller.evaluate(snapshot) for snapshot in stable_snapshots]
        self.assertFalse(decisions[0].stop)
        self.assertFalse(decisions[1].stop)
        self.assertTrue(decisions[2].stop)
        self.assertEqual(decisions[2].reason, "article_bottom_stable")

    def test_worker_dispatch_uses_injected_executor_for_multiple_tasks(self) -> None:
        captured_workers: list[int] = []

        class FakeFuture:
            def __init__(self, result):
                self._result = result

            def result(self):
                return self._result

        class FakeExecutor:
            def __init__(self, max_workers: int):
                captured_workers.append(max_workers)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def submit(self, func, task, config):
                return FakeFuture(func(task, config))

        def fake_archive(task: ArticleHtmlArchiveTask, config: ArticleHtmlArchiveConfig):
            return {"ok": True, "short_link": task.short_link, "headless": config.headless}

        tasks = [
            ArticleHtmlArchiveTask(
                article_id=1,
                short_link="https://mp.weixin.qq.com/s/a",
                account_name="账号",
                published_article_time="2026-06-20 10:30",
                article_title="A",
                storage_root=Path("storages"),
            ),
            ArticleHtmlArchiveTask(
                article_id=2,
                short_link="https://mp.weixin.qq.com/s/b",
                account_name="账号",
                published_article_time="2026-06-20 10:31",
                article_title="B",
                storage_root=Path("storages"),
            ),
        ]

        results = run_html_archive_tasks(
            tasks,
            ArticleHtmlArchiveConfig(concurrency=2, headless=True),
            archive_func=fake_archive,
            executor_factory=FakeExecutor,
        )

        self.assertEqual(captured_workers, [2])
        self.assertEqual([result["short_link"] for result in results], ["https://mp.weixin.qq.com/s/a", "https://mp.weixin.qq.com/s/b"])

    def test_scroll_warning_only_reports_real_scroll_limits(self) -> None:
        self.assertEqual(
            build_scroll_warning("max_scroll_seconds"),
            "页面较长，已达到滚动时间上限，可能有少量懒加载资源未完全保存",
        )
        self.assertEqual(
            build_scroll_warning("max_scrolls"),
            "页面较长，已达到最大滚动次数，可能有少量懒加载资源未完全保存",
        )
        self.assertEqual(build_scroll_warning("article_bottom_stable"), "")

    def test_missing_resource_selection_limits_and_deduplicates_candidates(self) -> None:
        candidates = ["https://res.wx.qq.com/a.png", "https://res.wx.qq.com/a.png"]
        candidates.extend(f"https://res.wx.qq.com/{index}.png" for index in range(500))

        selected = select_missing_resource_urls(
            candidates,
            resource_map={"https://res.wx.qq.com/0.png": "assets/img/0.png"},
            max_count=120,
        )

        self.assertEqual(len(selected), 120)
        self.assertEqual(selected[0], "https://res.wx.qq.com/a.png")
        self.assertNotIn("https://res.wx.qq.com/0.png", selected)
        self.assertEqual(len(selected), len(set(selected)))


if __name__ == "__main__":
    unittest.main()
