from __future__ import annotations

import html
import os
from pathlib import Path
import time
from typing import Any
from dataclasses import dataclass

from src.modules.archive.offline_html_rewriter import (
    rewrite_css_resource_links,
    rewrite_html_resource_links,
)
from src.modules.archive.offline_resource_store import save_offline_resource


CAPTURED_RESOURCE_TYPES = {"image", "media", "font", "stylesheet"}


@dataclass(frozen=True, slots=True)
class OfflineArchiveRequest:
    article_id: int
    article_title: str
    article_link: str
    stage_dir: Path
    browser_cache_dir: Path
    max_scroll_seconds: float
    max_scroll_count: int
    resource_timeout_seconds: float


@dataclass(frozen=True, slots=True)
class OfflineArchiveResult:
    ok: bool
    stage_dir: Path
    index_html_path: Path | None = None
    assets_dir: Path | None = None
    resource_count: int = 0
    message: str = ""
    warning: str = ""


class CapturedResponseStore:
    """保存 Playwright 页面本次加载产生的响应，不发起补充网络请求。"""

    def __init__(self, assets_dir: str | Path) -> None:
        self.assets_dir = Path(assets_dir)
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.resource_map: dict[str, str] = {}
        self.warnings: list[str] = []
        self.css_sources: dict[str, str] = {}

    def capture(self, response: Any) -> bool:
        url = str(getattr(response, "url", "") or "").strip()
        if not url or url in self.resource_map:
            return False
        request = getattr(response, "request", None)
        resource_type = str(getattr(request, "resource_type", "") or "").lower()
        headers = {
            str(key).lower(): str(value)
            for key, value in dict(getattr(response, "headers", {}) or {}).items()
        }
        content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if not _should_capture(resource_type, content_type):
            return False
        if _is_partial_media(response, content_type, headers):
            self.warnings.append(f"跳过分段媒体资源：{url}")
            return False
        try:
            body = response.body()
        except Exception as exc:
            self.warnings.append(f"读取页面响应失败：{url}：{exc}")
            return False
        if not body:
            return False
        saved = save_offline_resource(
            self.assets_dir,
            url=url,
            body=bytes(body),
            content_type=content_type,
        )
        self.resource_map[url] = saved.relative_path
        if content_type == "text/css":
            self.css_sources[saved.relative_path] = url
        return True

    def rewrite_saved_css(self) -> None:
        root = self.assets_dir.parent
        for relative_path, source_url in self.css_sources.items():
            css_path = root / relative_path
            try:
                css_text = css_path.read_text(encoding="utf-8", errors="ignore")
                # CSS 内的 URL 以 CSS 文件目录为基准，不能直接复用 HTML 的 assets/... 路径。
                css_resource_map = {
                    url: Path(
                        os.path.relpath(root / local_path, start=css_path.parent)
                    ).as_posix()
                    for url, local_path in self.resource_map.items()
                }
                css_path.write_text(
                    rewrite_css_resource_links(
                        css_text,
                        css_resource_map,
                        base_url=source_url,
                    ),
                    encoding="utf-8",
                )
            except OSError as exc:
                self.warnings.append(f"重写样式资源失败：{source_url}：{exc}")


def archive_offline_article(
    request: OfflineArchiveRequest,
    *,
    on_event=None,
) -> OfflineArchiveResult:
    """使用独立 Playwright 浏览器归档一篇文章，所有资源来自本次页面响应。"""
    stage_dir = Path(request.stage_dir)
    assets_dir = stage_dir / "assets"
    stage_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(request.browser_cache_dir)
    _emit(on_event, "启动浏览器", 0.0)

    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        return OfflineArchiveResult(
            ok=False,
            stage_dir=stage_dir,
            assets_dir=assets_dir,
            message="当前环境未安装 Playwright",
        )

    started_at = time.monotonic()
    resource_store = CapturedResponseStore(assets_dir)
    browser = None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1365, "height": 1600})
            page = context.new_page()
            page.set_default_timeout(max(500, int(request.resource_timeout_seconds * 1000)))
            page.on("response", resource_store.capture)

            _emit(on_event, "打开文章", time.monotonic() - started_at)
            page.goto(
                request.article_link,
                wait_until="domcontentloaded",
                timeout=max(30000, int(request.resource_timeout_seconds * 1000)),
            )
            page.wait_for_timeout(500)
            _scroll_page(
                page,
                resource_store=resource_store,
                max_scroll_seconds=request.max_scroll_seconds,
                max_scroll_count=request.max_scroll_count,
                started_at=started_at,
                on_event=on_event,
            )
            page.wait_for_timeout(300)

            _emit(on_event, "整理离线页面", time.monotonic() - started_at)
            snapshot = _extract_rendered_article(page)
            page_url = str(getattr(page, "url", "") or request.article_link)
            rendered_html = _build_offline_html(
                title=str(snapshot.get("title") or request.article_title),
                meta=str(snapshot.get("meta") or ""),
                content=str(snapshot.get("content") or ""),
                tool=str(snapshot.get("tool") or ""),
            )
            rewritten_html = rewrite_html_resource_links(
                rendered_html,
                resource_store.resource_map,
                base_url=page_url,
            )
            resource_store.rewrite_saved_css()
            index_path = stage_dir / "index.html"
            index_path.write_text(rewritten_html, encoding="utf-8")
            browser.close()
            browser = None

        warning = "；".join(resource_store.warnings[:10])
        return OfflineArchiveResult(
            ok=True,
            stage_dir=stage_dir,
            index_html_path=index_path,
            assets_dir=assets_dir,
            resource_count=len(resource_store.resource_map),
            message="离线缓存完成",
            warning=warning,
        )
    except Exception as exc:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        return OfflineArchiveResult(
            ok=False,
            stage_dir=stage_dir,
            assets_dir=assets_dir,
            resource_count=len(resource_store.resource_map),
            message=f"离线缓存失败：{type(exc).__name__}: {exc}",
            warning="；".join(resource_store.warnings[:10]),
        )


def _scroll_page(
    page: Any,
    *,
    resource_store: CapturedResponseStore,
    max_scroll_seconds: float,
    max_scroll_count: int,
    started_at: float,
    on_event,
) -> None:
    stable_rounds = 0
    previous_snapshot: tuple[int, int] | None = None
    for scroll_count in range(max(1, int(max_scroll_count))):
        elapsed = time.monotonic() - started_at
        if elapsed >= max(0.0, float(max_scroll_seconds)):
            resource_store.warnings.append("已达到最长滚动加载时间")
            break
        snapshot = page.evaluate(
            """() => {
                const root = document.scrollingElement || document.documentElement;
                const height = Math.max(root.scrollHeight, document.body ? document.body.scrollHeight : 0);
                const top = root.scrollTop || window.scrollY || 0;
                const viewport = window.innerHeight || document.documentElement.clientHeight || 1;
                window.scrollBy(0, Math.max(240, Math.floor(viewport * 0.8)));
                return { top, height, viewport };
            }"""
        )
        page.wait_for_timeout(180)
        top = int(snapshot.get("top") or 0)
        height = int(snapshot.get("height") or 0)
        viewport = int(snapshot.get("viewport") or 1)
        current = (height, len(resource_store.resource_map))
        stable_rounds = stable_rounds + 1 if current == previous_snapshot else 0
        previous_snapshot = current
        _emit(
            on_event,
            f"页面滚动 {scroll_count + 1}/{max_scroll_count}",
            time.monotonic() - started_at,
        )
        if top + viewport >= height - 10 and stable_rounds >= 2:
            break
    else:
        resource_store.warnings.append("已达到最大滚动次数")


def _extract_rendered_article(page: Any) -> dict[str, str]:
    return dict(
        page.evaluate(
            """() => {
                const content = document.querySelector('#js_content')
                    || document.querySelector('.rich_media_content')
                    || document.querySelector('article')
                    || document.body;
                const clone = content ? content.cloneNode(true) : null;
                if (clone) {
                    clone.querySelectorAll('script, iframe, noscript').forEach(node => node.remove());
                    clone.querySelectorAll('img').forEach(node => {
                        const candidate = node.currentSrc || node.getAttribute('data-src')
                            || node.getAttribute('data-original') || node.getAttribute('src') || '';
                        if (candidate && !candidate.startsWith('data:')) node.setAttribute('src', candidate);
                    });
                }
                const meta = document.querySelector('#meta_content')
                    || document.querySelector('.rich_media_meta_list');
                const tool = document.querySelector('#js_article_bottom_bar')
                    || document.querySelector('.rich_media_tool');
                return {
                    title: (document.querySelector('#activity-name')?.textContent || document.title || '').trim(),
                    meta: meta ? meta.innerHTML : '',
                    content: clone ? clone.innerHTML : '',
                    tool: tool ? tool.innerHTML : ''
                };
            }"""
        )
        or {}
    )


def _build_offline_html(*, title: str, meta: str, content: str, tool: str) -> str:
    safe_title = html.escape(title.strip() or "微信文章")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <style>
    body {{ margin: 0; color: rgba(0,0,0,.9); font-family: "PingFang SC", "Microsoft YaHei", sans-serif; background: #fff; }}
    article {{ width: min(677px, calc(100vw - 32px)); margin: 0 auto; padding: 20px 0 48px; }}
    h1 {{ margin: 0 0 14px; font-size: 22px; line-height: 1.4; }}
    .meta {{ margin-bottom: 22px; color: rgba(0,0,0,.45); font-size: 15px; }}
    .content {{ font-size: 17px; line-height: 1.7; overflow-wrap: break-word; }}
    .content img, .content video {{ max-width: 100% !important; height: auto !important; }}
    .tool {{ margin-top: 32px; color: #576b95; }}
  </style>
</head>
<body>
  <article>
    <h1>{safe_title}</h1>
    <div class="meta">{meta}</div>
    <div class="content" id="js_content">{content}</div>
    <div class="tool">{tool}</div>
  </article>
</body>
</html>"""


def _emit(callback, name: str, elapsed_seconds: float) -> None:
    if callback is None:
        return
    callback(
        {
            "name": name,
            "status": "running",
            "elapsed_seconds": round(max(0.0, elapsed_seconds), 3),
        }
    )


def _should_capture(resource_type: str, content_type: str) -> bool:
    return resource_type in CAPTURED_RESOURCE_TYPES or content_type.startswith(
        ("image/", "video/", "audio/", "font/")
    ) or content_type == "text/css"


def _is_partial_media(response: Any, content_type: str, headers: dict[str, str]) -> bool:
    if not content_type.startswith(("video/", "audio/")):
        return False
    return int(getattr(response, "status", 0) or 0) == 206 or bool(headers.get("content-range"))


__all__ = [
    "CapturedResponseStore",
    "OfflineArchiveRequest",
    "OfflineArchiveResult",
    "archive_offline_article",
]
