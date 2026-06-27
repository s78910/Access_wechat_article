from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urljoin, urlparse


RESOURCE_ATTRS = (
    "src",
    "href",
    "poster",
    "data-src",
    "data-original",
    "data-original-src",
    "data-lazy-src",
    "data-actualsrc",
    "data-echo",
)

URL_FUNC_RE = re.compile(r"url\(\s*(['\"]?)(?P<url>[^'\"\)]+)\1\s*\)", re.IGNORECASE)
ATTR_RE = re.compile(
    r"(?P<prefix>\b(?P<name>[a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*)(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
    re.DOTALL,
)


def rewrite_html_resource_links(html_text: str, resource_map: dict[str, str], *, base_url: str) -> str:
    def replace_attr(match: re.Match[str]) -> str:
        name = match.group("name").lower()
        value = match.group("value")
        quote = match.group("quote")
        prefix = match.group("prefix")
        if name in RESOURCE_ATTRS:
            return f"{prefix}{quote}{_rewrite_single_url(value, resource_map, base_url)}{quote}"
        if name == "srcset":
            return f"{prefix}{quote}{_rewrite_srcset(value, resource_map, base_url)}{quote}"
        if name == "style":
            return f"{prefix}{quote}{rewrite_css_urls(value, resource_map, base_url=base_url)}{quote}"
        return match.group(0)

    return ATTR_RE.sub(replace_attr, html_text)


def rewrite_css_urls(css_text: str, resource_map: dict[str, str], *, base_url: str) -> str:
    def replace_url(match: re.Match[str]) -> str:
        raw_url = match.group("url").strip()
        local = _rewrite_single_url(raw_url, resource_map, base_url)
        return f"url('{local}')"

    return URL_FUNC_RE.sub(replace_url, css_text)


def extract_resource_urls_from_html(html_text: str, *, base_url: str) -> list[str]:
    urls: list[str] = []
    for match in ATTR_RE.finditer(html_text):
        name = match.group("name").lower()
        value = match.group("value")
        if name in RESOURCE_ATTRS:
            _append_url(urls, value, base_url)
        elif name == "srcset":
            for item in _split_srcset(value):
                _append_url(urls, item[0], base_url)
        elif name == "style":
            urls.extend(extract_resource_urls_from_css(value, base_url=base_url))
    return _unique_urls(urls)


def extract_resource_urls_from_css(css_text: str, *, base_url: str) -> list[str]:
    urls: list[str] = []
    for match in URL_FUNC_RE.finditer(css_text):
        _append_url(urls, match.group("url").strip(), base_url)
    return _unique_urls(urls)


def resolve_resource_url(value: str, base_url: str) -> str:
    text = str(value or "").strip()
    if not text or _should_skip_url(text):
        return ""
    if text.startswith("//"):
        text = f"https:{text}"
    absolute = urljoin(base_url, text)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"}:
        return ""
    if parsed.fragment and not parsed.path:
        return ""
    if "%23" in parsed.path and not Path(parsed.path).suffix:
        return ""
    if _looks_like_domain_root(parsed.path):
        return ""
    return absolute


def _rewrite_single_url(value: str, resource_map: dict[str, str], base_url: str) -> str:
    absolute = resolve_resource_url(value, base_url)
    if not absolute:
        return value
    return resource_map.get(absolute) or resource_map.get(value) or value


def _rewrite_srcset(value: str, resource_map: dict[str, str], base_url: str) -> str:
    parts: list[str] = []
    for url, descriptor in _split_srcset(value):
        local = _rewrite_single_url(url, resource_map, base_url)
        parts.append(f"{local} {descriptor}".strip())
    return ", ".join(parts)


def _split_srcset(value: str) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for raw_item in str(value or "").split(","):
        text = raw_item.strip()
        if not text:
            continue
        pieces = text.split(None, 1)
        url = pieces[0]
        descriptor = pieces[1] if len(pieces) > 1 else ""
        items.append((url, descriptor))
    return items


def _append_url(urls: list[str], value: str, base_url: str) -> None:
    absolute = resolve_resource_url(value, base_url)
    if absolute:
        urls.append(absolute)


def _unique_urls(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _should_skip_url(value: str) -> bool:
    lower = value.lower()
    return lower.startswith(("data:", "blob:", "javascript:", "mailto:", "tel:", "#"))


def _looks_like_domain_root(path: str) -> bool:
    normalized = str(path or "").strip()
    if normalized in {"", "/"}:
        return True
    suffix = Path(normalized).suffix
    return not suffix and normalized.count("/") <= 1


__all__ = [
    "extract_resource_urls_from_css",
    "extract_resource_urls_from_html",
    "resolve_resource_url",
    "rewrite_css_urls",
    "rewrite_html_resource_links",
]
