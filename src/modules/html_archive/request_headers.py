from __future__ import annotations

import random

from src.modules.html_archive.models import ArticleHtmlArchiveConfig


LANGUAGE_POOL = (
    "zh-CN,zh;q=0.9,en;q=0.8",
    "zh-CN,zh;q=0.9",
    "zh-CN,zh-Hans;q=0.9,en-US;q=0.8,en;q=0.7",
)


def build_random_browser_headers(config: ArticleHtmlArchiveConfig) -> dict[str, str]:
    random_source = random.SystemRandom()
    user_agent = random_source.choice(config.user_agent_pool)
    language = random_source.choice(LANGUAGE_POOL)
    return {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": language,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }


__all__ = ["build_random_browser_headers"]
