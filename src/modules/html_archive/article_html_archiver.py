from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from src.modules.html_archive.html_rewriter import (
    extract_resource_urls_from_css,
    extract_resource_urls_from_html,
    rewrite_css_urls,
    rewrite_html_resource_links,
)
from src.modules.html_archive.models import ArticleHtmlArchiveConfig, ArticleHtmlArchiveResult, ArticleHtmlArchiveTask
from src.modules.html_archive.request_headers import build_random_browser_headers
from src.modules.html_archive.resource_store import infer_asset_kind, save_asset
from src.modules.html_archive.scroll_strategy import AdaptiveScrollController, ScrollSnapshot
from src.modules.html_archive.url_guard import normalize_plain_wechat_short_link
from src.modules.storage.path_builder import build_article_archive_dir
from src.modules.utils.file_utils import clean_path_part
from src.modules.utils.time_utils import format_datetime_for_dir


LAZY_IMAGE_SCRIPT = """
() => {
  const lazyAttrs = [
    'data-src',
    'data-original',
    'data-original-src',
    'data-lazy-src',
    'data-actualsrc',
    'data-echo',
    'data-backsrc'
  ];
  let updated = 0;
  document.querySelectorAll('img').forEach((img) => {
    for (const attr of lazyAttrs) {
      const value = img.getAttribute(attr);
      if (!value || !value.trim() || value.startsWith('data:image')) {
        continue;
      }
      const current = img.getAttribute('src') || '';
      if (!current || current.startsWith('data:image') || current.includes('blank')) {
        img.setAttribute('src', value);
        updated += 1;
        break;
      }
    }
  });
  return updated;
}
"""

SNAPSHOT_SCRIPT = """
() => {
  const article = document.querySelector('#js_content')
    || document.querySelector('.rich_media_content')
    || document.body;
  const rect = article.getBoundingClientRect();
  const scrollTop = window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0;
  const targetBottom = Math.max(0, Math.ceil(rect.bottom + scrollTop));
  const lazyAttrs = [
    'data-src',
    'data-original',
    'data-original-src',
    'data-lazy-src',
    'data-actualsrc',
    'data-echo',
    'data-backsrc'
  ];
  let pendingLazyCount = 0;
  document.querySelectorAll('img').forEach((img) => {
    const src = img.getAttribute('src') || '';
    for (const attr of lazyAttrs) {
      const value = img.getAttribute(attr);
      if (value && value.trim() && !value.startsWith('data:image') && (!src || src.startsWith('data:image') || src.includes('blank'))) {
        pendingLazyCount += 1;
        break;
      }
    }
  });
  return {
    scrollTop: Math.ceil(scrollTop),
    viewportHeight: window.innerHeight || document.documentElement.clientHeight || 1,
    scrollHeight: Math.max(
      document.body.scrollHeight || 0,
      document.documentElement.scrollHeight || 0,
      targetBottom
    ),
    targetBottom,
    imageCount: document.images.length,
    pendingLazyCount,
  };
}
"""


def archive_article_html(task: ArticleHtmlArchiveTask, config: ArticleHtmlArchiveConfig | None = None) -> ArticleHtmlArchiveResult:
    """用 Playwright 把一篇微信短链接文章保存为 index.html 和 assets。"""
    config = config or ArticleHtmlArchiveConfig()
    short_link = normalize_plain_wechat_short_link(task.short_link)
    if not short_link:
        return ArticleHtmlArchiveResult(ok=False, message="文章链接不是不带参数的微信短链接")

    archive_dir = resolve_article_html_archive_dir(task)
    assets_dir = archive_dir / config.resource_dir_name
    archive_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(Path(config.browser_cache_dir)))
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        return ArticleHtmlArchiveResult(
            ok=False,
            archive_dir=archive_dir,
            assets_dir=assets_dir,
            message="当前 Python 环境未安装 Playwright，请先使用 uv add playwright",
        )

    resource_map: dict[str, str] = {}
    css_sources: dict[str, str] = {}
    failed_resources: list[str] = []
    warning = ""

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=config.headless)
            headers = build_random_browser_headers(config)
            context = browser.new_context(
                viewport={"width": config.viewport_width, "height": config.viewport_height},
                user_agent=headers["User-Agent"],
                extra_http_headers=headers,
            )
            context.set_default_timeout(config.resource_request_timeout_ms)
            page = context.new_page()

            def handle_response(response: Any) -> None:
                try:
                    content_type = str(response.headers.get("content-type") or "")
                    kind = infer_asset_kind(response.url, content_type)
                    if kind not in {"img", "css", "js", "font"}:
                        return
                    body = response.body()
                    if not body:
                        return
                    saved = save_asset(assets_dir, url=response.url, data=body, content_type=content_type)
                    resource_map[response.url] = saved.relative_path
                    if saved.kind == "css":
                        css_sources[saved.relative_path] = response.url
                except Exception:
                    failed_resources.append(str(getattr(response, "url", "")))

            page.on("response", handle_response)
            page.goto(short_link, wait_until=config.wait_until, timeout=config.navigation_timeout_ms)
            page.wait_for_timeout(config.initial_wait_ms)
            scroll_stop_reason = _scroll_until_loaded(page, config, resource_map)
            warning = build_scroll_warning(scroll_stop_reason)
            _download_lazy_resources(page, assets_dir, resource_map, css_sources, failed_resources, config)
            _rewrite_saved_css_files(assets_dir, resource_map, css_sources)
            html_content = rewrite_html_resource_links(page.content(), resource_map, base_url=page.url)
            index_html_path = archive_dir / "index.html"
            index_html_path.write_text(html_content, encoding="utf-8")
            try:
                page.wait_for_load_state("networkidle", timeout=config.network_idle_timeout_ms)
            except PlaywrightTimeoutError:
                warning = "页面网络请求未完全空闲，已保存当前可见内容"
            browser.close()

        return ArticleHtmlArchiveResult(
            ok=True,
            archive_dir=archive_dir,
            index_html_path=archive_dir / "index.html",
            assets_dir=assets_dir,
            resource_count=len(resource_map),
            failed_resources=tuple(item for item in failed_resources if item),
            message="HTML 离线归档完成",
            warning=warning,
        )
    except Exception as exc:
        return ArticleHtmlArchiveResult(
            ok=False,
            archive_dir=archive_dir,
            assets_dir=assets_dir,
            resource_count=len(resource_map),
            failed_resources=tuple(item for item in failed_resources if item),
            message=f"HTML 离线归档失败：{exc}",
            warning=warning,
        )


def resolve_article_html_archive_dir(task: ArticleHtmlArchiveTask) -> Path:
    exact_dir = (
        Path(task.storage_root)
        / clean_path_part(task.account_name)
        / f"{format_datetime_for_dir(task.published_article_time)} {clean_path_part(task.article_title)}".strip()
    )
    if exact_dir.exists():
        return exact_dir
    return build_article_archive_dir(
        storage_root=task.storage_root,
        account_name=task.account_name,
        published_time=task.published_article_time,
        article_title=task.article_title,
    )


def build_scroll_warning(stop_reason: str) -> str:
    if stop_reason == "max_scroll_seconds":
        return "页面较长，已达到滚动时间上限，可能有少量懒加载资源未完全保存"
    if stop_reason == "max_scrolls":
        return "页面较长，已达到最大滚动次数，可能有少量懒加载资源未完全保存"
    return ""


def select_missing_resource_urls(candidates: list[str], resource_map: dict[str, str], max_count: int) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for url in candidates:
        if not url or url in resource_map or url in seen:
            continue
        seen.add(url)
        selected.append(url)
        if len(selected) >= max(0, int(max_count)):
            break
    return selected


def _scroll_until_loaded(page: Any, config: ArticleHtmlArchiveConfig, resource_map: dict[str, str]) -> str:
    controller = AdaptiveScrollController(config)
    start = time.monotonic()
    stop_reason = "continue"
    for scroll_count in range(config.max_scrolls + 1):
        page.evaluate(LAZY_IMAGE_SCRIPT)
        raw = page.evaluate(SNAPSHOT_SCRIPT)
        snapshot = ScrollSnapshot(
            scroll_top=int(raw.get("scrollTop") or 0),
            viewport_height=int(raw.get("viewportHeight") or config.viewport_height),
            scroll_height=int(raw.get("scrollHeight") or 0),
            target_bottom=int(raw.get("targetBottom") or raw.get("scrollHeight") or 0),
            image_count=int(raw.get("imageCount") or 0),
            pending_lazy_count=int(raw.get("pendingLazyCount") or 0),
            resource_count=len(resource_map),
            elapsed_seconds=time.monotonic() - start,
            scroll_count=scroll_count,
        )
        decision = controller.evaluate(snapshot)
        if decision.stop:
            stop_reason = decision.reason
            break
        page.evaluate("(distance) => window.scrollBy(0, distance)", controller.next_scroll_distance(snapshot))
        page.wait_for_timeout(config.scroll_delay_ms)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(config.scroll_delay_ms)
    return stop_reason


def _download_lazy_resources(
    page: Any,
    assets_dir: Path,
    resource_map: dict[str, str],
    css_sources: dict[str, str],
    failed_resources: list[str],
    config: ArticleHtmlArchiveConfig,
) -> None:
    extra_download_count = 0
    html_candidates = select_missing_resource_urls(
        extract_resource_urls_from_html(page.content(), base_url=page.url),
        resource_map,
        config.max_extra_resource_downloads,
    )
    for url in html_candidates:
        _download_resource(page, assets_dir, url, resource_map, css_sources, failed_resources, config.resource_request_timeout_ms)
        extra_download_count += 1

    remaining_budget = max(0, config.max_extra_resource_downloads - extra_download_count)
    if remaining_budget <= 0:
        return
    for relative_path, css_url in list(css_sources.items()):
        css_path = assets_dir.parent / relative_path
        try:
            css_text = css_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for resource_url in select_missing_resource_urls(
            extract_resource_urls_from_css(css_text, base_url=css_url),
            resource_map,
            remaining_budget,
        ):
            _download_resource(
                page,
                assets_dir,
                resource_url,
                resource_map,
                css_sources,
                failed_resources,
                config.resource_request_timeout_ms,
            )
            remaining_budget = max(0, remaining_budget - 1)
            if remaining_budget <= 0:
                return


def _download_resource(
    page: Any,
    assets_dir: Path,
    url: str,
    resource_map: dict[str, str],
    css_sources: dict[str, str],
    failed_resources: list[str],
    timeout_ms: int,
) -> None:
    if url in resource_map:
        return
    try:
        response = page.request.get(url, timeout=max(500, int(timeout_ms)))
        if not response.ok:
            failed_resources.append(url)
            return
        content_type = str(response.headers.get("content-type") or "")
        saved = save_asset(assets_dir, url=url, data=response.body(), content_type=content_type)
        resource_map[url] = saved.relative_path
        if saved.kind == "css":
            css_sources[saved.relative_path] = url
    except Exception:
        failed_resources.append(url)


def _rewrite_saved_css_files(assets_dir: Path, resource_map: dict[str, str], css_sources: dict[str, str]) -> None:
    for relative_path, source_url in css_sources.items():
        css_path = assets_dir.parent / relative_path
        try:
            css_text = css_path.read_text(encoding="utf-8", errors="ignore")
            css_path.write_text(rewrite_css_urls(css_text, resource_map, base_url=source_url), encoding="utf-8")
        except OSError:
            continue


__all__ = [
    "archive_article_html",
    "build_scroll_warning",
    "resolve_article_html_archive_dir",
    "select_missing_resource_urls",
]
