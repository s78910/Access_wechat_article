from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.core.config import PROJECT_ROOT


@dataclass(frozen=True)
class ArticleHtmlArchiveTask:
    article_id: int
    short_link: str
    account_name: str
    published_article_time: str
    article_title: str
    storage_root: Path


@dataclass(frozen=True)
class ArticleHtmlArchiveConfig:
    headless: bool = True
    concurrency: int = 2
    resource_dir_name: str = "assets"
    browser_cache_dir: Path = PROJECT_ROOT / ".playwright-browsers"
    bypass_system_proxy: bool = True
    chromium_launch_args: tuple[str, ...] = ()
    viewport_width: int = 1365
    viewport_height: int = 1600
    wait_until: str = "domcontentloaded"
    navigation_timeout_ms: int = 45000
    network_idle_timeout_ms: int = 8000
    initial_wait_ms: int = 500
    scroll_delay_ms: int = 180
    scroll_step_ratio: float = 0.8
    stable_rounds: int = 3
    short_page_stable_rounds: int = 1
    max_scrolls: int = 300
    max_scroll_seconds: float = 90.0
    resource_request_timeout_ms: int = 2000
    max_extra_resource_downloads: int = 120
    user_agent_pool: tuple[str, ...] = field(
        default_factory=lambda: (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        )
    )


@dataclass(frozen=True)
class ArticleHtmlArchiveResult:
    ok: bool
    archive_dir: Path | None = None
    index_html_path: Path | None = None
    assets_dir: Path | None = None
    resource_count: int = 0
    failed_resources: tuple[str, ...] = ()
    message: str = ""
    warning: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "archive_dir": str(self.archive_dir or ""),
            "index_html_path": str(self.index_html_path or ""),
            "assets_dir": str(self.assets_dir or ""),
            "resource_count": self.resource_count,
            "failed_resources": list(self.failed_resources),
            "message": self.message,
            "warning": self.warning,
        }
