from __future__ import annotations

import html
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from src.modules.html_archive.html_rewriter import (
    bind_read_original_link_in_html,
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

ARTICLE_HTML_SCRIPT = """
() => {
  const title = document.querySelector('#activity-name')?.innerHTML
    || document.querySelector('h1')?.innerHTML
    || document.title
    || '';
  const meta = document.querySelector('#meta_content')?.innerHTML || '';
  const contentNode = document.querySelector('#js_content')
    || document.querySelector('.rich_media_content');
  const content = contentNode?.innerHTML || '';
  const tool = document.querySelector('.rich_media_tool')?.innerHTML
    || document.querySelector('#js_toobar3')?.innerHTML
    || document.querySelector('#js_pc_qr_code')?.innerHTML
    || '';
  const sourceUrl = window.msg_source_url || window.msgSourceUrl || '';
  const pageMid = window.PAGE_MID || '';
  const bodyText = document.body?.innerText || '';
  const pageHtml = document.documentElement?.innerHTML || '';
  const isVerifyPage = pageMid.includes('secitptpage/verify')
    || pageHtml.includes('captcha.gtimg.com')
    || pageHtml.includes('TCaptcha')
    || bodyText.includes('验证码')
    || bodyText.includes('尝试太多');
  return {
    title,
    meta,
    content,
    tool,
    sourceUrl,
    pageMid,
    bodyText,
    isVerifyPage,
    hasArticleContent: Boolean(contentNode && content.trim())
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
    prepare_archive_output_dirs(archive_dir, assets_dir)

    ensure_playwright_browser_path(config)
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
    unavailable_reason = ""

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
            page.goto(short_link, wait_until=config.wait_until, timeout=config.navigation_timeout_ms)
            page.wait_for_timeout(config.initial_wait_ms)
            scroll_stop_reason = _scroll_until_loaded(page, config, resource_map)
            warning = build_scroll_warning(scroll_stop_reason)
            article_snapshot = _extract_article_snapshot(page)
            source_url = _extract_read_original_url(page, str(article_snapshot.get("sourceUrl") or ""))
            unavailable_reason = is_unavailable_article_snapshot(article_snapshot)
            if unavailable_reason:
                html_content = build_unavailable_article_html(
                    title=task.article_title or str(article_snapshot.get("title") or ""),
                    reason=unavailable_reason,
                    source_url=short_link,
                )
            else:
                article_html = build_article_only_html(
                    title=str(article_snapshot.get("title") or ""),
                    meta=str(article_snapshot.get("meta") or ""),
                    content=str(article_snapshot.get("content") or ""),
                    tool=str(article_snapshot.get("tool") or ""),
                )
                if source_url:
                    article_html = bind_read_original_link_in_html(article_html, source_url)
                _download_lazy_resources(page, article_html, assets_dir, resource_map, css_sources, failed_resources, config)
                _rewrite_saved_css_files(assets_dir, resource_map, css_sources)
                html_content = rewrite_html_resource_links(article_html, resource_map, base_url=page.url)
            index_html_path = archive_dir / "index.html"
            index_html_path.write_text(html_content, encoding="utf-8")
            try:
                page.wait_for_load_state("networkidle", timeout=config.network_idle_timeout_ms)
            except PlaywrightTimeoutError:
                warning = "页面网络请求未完全空闲，已保存当前可见内容"
            browser.close()

        if unavailable_reason:
            return ArticleHtmlArchiveResult(
                ok=False,
                archive_dir=archive_dir,
                index_html_path=archive_dir / "index.html",
                assets_dir=assets_dir,
                resource_count=len(resource_map),
                failed_resources=tuple(item for item in failed_resources if item),
                message=f"HTML 离线归档未完成：{unavailable_reason}",
                warning=unavailable_reason,
            )

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


def ensure_playwright_browser_path(config: ArticleHtmlArchiveConfig) -> Path:
    browser_dir = Path(config.browser_cache_dir)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_dir)
    return browser_dir


def prepare_archive_output_dirs(archive_dir: Path, assets_dir: Path) -> None:
    archive_path = Path(archive_dir)
    assets_path = Path(assets_dir)
    archive_path.mkdir(parents=True, exist_ok=True)
    if assets_path.exists():
        resolved_archive = archive_path.resolve()
        resolved_assets = assets_path.resolve()
        if resolved_assets == resolved_archive or resolved_archive not in resolved_assets.parents:
            raise ValueError("assets_dir 必须位于当前文章归档目录下")
        shutil.rmtree(resolved_assets)
    assets_path.mkdir(parents=True, exist_ok=True)


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


def should_save_article_resource(url: str, content_type: str) -> bool:
    content = str(content_type or "").lower().split(";", 1)[0].strip()
    if content.startswith(("image/", "video/", "audio/")):
        return True
    return infer_asset_kind(url, content_type) == "img"


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
    html_text: str,
    assets_dir: Path,
    resource_map: dict[str, str],
    css_sources: dict[str, str],
    failed_resources: list[str],
    config: ArticleHtmlArchiveConfig,
) -> None:
    extra_download_count = 0
    html_candidates = select_missing_resource_urls(
        extract_resource_urls_from_html(html_text, base_url=page.url),
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
        if not should_save_article_resource(url, content_type):
            return
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


def _extract_article_snapshot(page: Any) -> dict[str, object]:
    try:
        return dict(page.evaluate(ARTICLE_HTML_SCRIPT) or {})
    except Exception:
        return {
            "title": "",
            "meta": "",
            "content": "",
            "tool": "",
            "sourceUrl": "",
            "pageMid": "",
            "bodyText": "",
            "isVerifyPage": False,
            "hasArticleContent": False,
        }


def is_unavailable_article_snapshot(snapshot: dict[str, object]) -> str:
    page_mid = str(snapshot.get("pageMid") or "")
    body_text = str(snapshot.get("bodyText") or "")
    content = str(snapshot.get("content") or "")
    if bool(snapshot.get("isVerifyPage")) or "secitptpage/verify" in page_mid or "验证码" in body_text:
        return "微信返回了验证页，需要人工验证后重试"
    if not bool(snapshot.get("hasArticleContent")) or not content.strip():
        return "未获取到文章正文"
    return ""


def build_unavailable_article_html(*, title: str, reason: str, source_url: str) -> str:
    safe_title = html.escape(_strip_tags(title) or "文章正文暂不可用")
    safe_reason = html.escape(reason or "未获取到文章正文")
    safe_source = html.escape(str(source_url or ""), quote=True)
    source_link = (
        f'<p class="source-link"><a href="{safe_source}" target="_blank" rel="noopener noreferrer">打开原始短链接</a></p>'
        if safe_source.startswith(("http://", "https://"))
        else ""
    )
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <style>
    body {{
      margin: 0 auto;
      max-width: 720px;
      padding: 40px 18px;
      color: #1f2329;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.75;
      background: #fff;
    }}
    h1 {{ font-size: 22px; line-height: 1.35; }}
    .notice {{
      margin-top: 20px;
      padding: 16px;
      border: 1px solid #d9e2f2;
      background: #f7faff;
      color: #40516b;
    }}
    a {{ color: #576b95; text-decoration: none; }}
  </style>
</head>
<body>
  <article>
    <h1>{safe_title}</h1>
    <div class="notice">未获取到文章正文：{safe_reason}</div>
    {source_link}
  </article>
</body>
</html>"""


def clean_article_content_html(content: str) -> str:
    """清理微信正文中会被本地模板放大的空标题块，保留正文真实换行和媒体节点。"""
    cleaned = str(content or "")
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = re.sub(
            r"<(?P<tag>h[1-6])\b(?P<attrs>[^>]*)>\s*(?:<span\b[^>]*>\s*)*<br\b[^>]*>\s*(?:</span>\s*)*</(?P=tag)>",
            r'<p\g<attrs>><br></p>',
            cleaned,
            flags=re.IGNORECASE | re.DOTALL,
        )
        cleaned = re.sub(
            r"<h[1-6]\b[^>]*>\s*(?:<span\b[^>]*>\s*)*(?:&nbsp;|\s)*(?:</span>\s*)*</h[1-6]>",
            "",
            cleaned,
            flags=re.IGNORECASE | re.DOTALL,
        )
    return cleaned


def build_article_only_html(*, title: str, meta: str, content: str, tool: str) -> str:
    # 只保留文章标题、元信息、正文和底部工具区，避免把微信页面壳资源一起离线化。
    cleaned_content = clean_article_content_html(content)
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_strip_tags(title) or "WeChat Article"}</title>
  <style>
    html {{
      background: #fff;
    }}
    body {{
      margin: 0;
      padding: 0;
      color: rgba(0, 0, 0, 0.9);
      font-family: mp-quote, "PingFang SC", system-ui, -apple-system, BlinkMacSystemFont, "Helvetica Neue", "Hiragino Sans GB", "Microsoft YaHei UI", "Microsoft YaHei", Arial, sans-serif;
      background: #fff;
      overflow-x: hidden;
    }}
    .article-page {{
      width: min(677px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 20px 0 48px;
      box-sizing: border-box;
    }}
    .article-title {{
      margin: 0 0 14px;
      font-size: 22px;
      line-height: 1.4;
      font-weight: 700;
      color: rgba(0, 0, 0, 0.9);
      overflow-wrap: break-word;
    }}
    .article-meta {{
      margin: 0 0 22px;
      color: rgba(0, 0, 0, 0.3);
      font-size: 0;
      line-height: 20px;
    }}
    .article-meta a {{
      color: #576b95;
      text-decoration: none;
    }}
    .article-meta em {{
      color: rgba(0, 0, 0, 0.3);
      font-style: normal;
    }}
    .article-meta .rich_media_meta {{
      display: inline-block;
      margin: 0 8px 10px 0;
      font-size: 15px;
      line-height: 20px;
      vertical-align: middle;
      font-style: normal;
    }}
    .article-meta .rich_media_meta_nickname {{
      color: #576b95;
    }}
    .article-meta .rich_media_meta_text {{
      color: rgba(0, 0, 0, 0.3);
    }}
    #js_profile_card,
    #meta_content_hide_info {{
      display: inline !important;
    }}
    #js_profile_card {{
      display: none !important;
    }}
    .article-content {{
      color: rgba(0, 0, 0, 0.9);
      font-size: 17px;
      line-height: 1.6;
      letter-spacing: 0.034em;
      overflow-wrap: break-word;
      word-break: normal;
    }}
    .article-content p,
    .article-content h1,
    .article-content h2,
    .article-content h3,
    .article-content h4,
    .article-content h5,
    .article-content h6,
    .article-content section {{
      margin: 0;
      max-width: 100%;
      box-sizing: border-box;
    }}
    .article-content img,
    .article-content video {{
      max-width: 100% !important;
      height: auto !important;
      box-sizing: border-box;
    }}
    .article-tool {{
      margin-top: 32px;
      color: #576b95;
      font-size: 15px;
      line-height: 1.6;
    }}
    .article-tool a {{
      color: #576b95;
      text-decoration: none;
    }}
  </style>
</head>
<body>
  <article class="article-page rich_media_area_primary_inner">
    <h1 class="article-title rich_media_title">{title}</h1>
    <div class="article-meta">{meta}</div>
    <div id="js_content" class="article-content rich_media_content">{cleaned_content}</div>
    <div class="article-tool">{tool}</div>
  </article>
</body>
</html>"""


def _extract_read_original_url(page: Any, html_text: str) -> str:
    try:
        value = page.evaluate("() => window.msg_source_url || window.msgSourceUrl || ''")
        if value:
            return str(value)
    except Exception:
        pass
    patterns = (
        r"msg_source_url\s*=\s*(['\"])(?P<url>.*?)\1",
        r"msgSourceUrl\s*=\s*(['\"])(?P<url>.*?)\1",
    )
    for pattern in patterns:
        match = re.search(pattern, html_text)
        if match:
            return match.group("url")
    return ""


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", str(value or "")).strip()


__all__ = [
    "archive_article_html",
    "build_article_only_html",
    "build_unavailable_article_html",
    "build_scroll_warning",
    "clean_article_content_html",
    "ensure_playwright_browser_path",
    "is_unavailable_article_snapshot",
    "prepare_archive_output_dirs",
    "resolve_article_html_archive_dir",
    "select_missing_resource_urls",
    "should_save_article_resource",
]
