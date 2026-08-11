from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse


RESOURCE_ATTRIBUTES = (
    "src",
    "href",
    "poster",
    "data-src",
    "data-original",
    "data-original-src",
    "data-lazy-src",
    "data-actualsrc",
)
ATTRIBUTE_PATTERN = re.compile(
    r"(?P<prefix>\b(?P<name>[a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*)"
    r"(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
    re.DOTALL,
)
CSS_URL_PATTERN = re.compile(
    r"url\(\s*(['\"]?)(?P<url>[^'\"\)]+)\1\s*\)",
    re.IGNORECASE,
)


def rewrite_html_resource_links(
    html_text: str,
    resource_map: dict[str, str],
    *,
    base_url: str,
) -> str:
    def replace_attribute(match: re.Match[str]) -> str:
        name = match.group("name").lower()
        value = match.group("value")
        quote = match.group("quote")
        prefix = match.group("prefix")
        if name in RESOURCE_ATTRIBUTES:
            value = _rewrite_url(value, resource_map, base_url)
        elif name == "srcset":
            value = _rewrite_srcset(value, resource_map, base_url)
        elif name == "style":
            value = rewrite_css_resource_links(value, resource_map, base_url=base_url)
        return f"{prefix}{quote}{value}{quote}"

    return ATTRIBUTE_PATTERN.sub(replace_attribute, html_text)


def rewrite_css_resource_links(
    css_text: str,
    resource_map: dict[str, str],
    *,
    base_url: str,
) -> str:
    return CSS_URL_PATTERN.sub(
        lambda match: f"url('{_rewrite_url(match.group('url'), resource_map, base_url)}')",
        css_text,
    )


def _rewrite_srcset(value: str, resource_map: dict[str, str], base_url: str) -> str:
    parts: list[str] = []
    for item in value.split(","):
        pieces = item.strip().split(None, 1)
        if not pieces:
            continue
        url = _rewrite_url(pieces[0], resource_map, base_url)
        descriptor = pieces[1] if len(pieces) > 1 else ""
        parts.append(f"{url} {descriptor}".strip())
    return ", ".join(parts)


def _rewrite_url(value: str, resource_map: dict[str, str], base_url: str) -> str:
    raw = value.strip()
    if not raw or raw.lower().startswith(("data:", "blob:", "javascript:", "#")):
        return value
    if raw.startswith("//"):
        raw = f"https:{raw}"
    absolute = urljoin(base_url, raw)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"}:
        return value
    return resource_map.get(absolute, resource_map.get(value, value))


__all__ = ["rewrite_css_resource_links", "rewrite_html_resource_links"]
