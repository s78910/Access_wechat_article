from __future__ import annotations

from dataclasses import dataclass, field
from http.cookies import SimpleCookie
import json
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from src.modules.request.article_html_requester import normalize_reference_url
from src.modules.request.chrome_headers import build_wechat_article_document_headers


WECHAT_ARTICLE_HOST = "mp.weixin.qq.com"
WECHAT_ARTICLE_PATH = "/s"


@dataclass(frozen=True, slots=True)
class OfflineNavigationState:
    """离线缓存打开文章时使用的导航状态；不向 UI 暴露临时凭据。"""

    mode: str = "stateless"
    url: str = ""
    user_agent: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    cookies: tuple[dict[str, Any], ...] = ()


def load_offline_navigation_state(
    *,
    enabled: bool,
    article_directory: str | Path | None = None,
    request_json_path: str | Path | None = None,
) -> OfflineNavigationState:
    """从 origin/request.json 读取微信内置浏览器状态，未启用时保持无状态。"""
    if not enabled:
        return OfflineNavigationState()

    evidence_path = _resolve_request_json_path(
        article_directory=article_directory,
        request_json_path=request_json_path,
    )
    evidence = _load_evidence(evidence_path)
    reference = evidence.get("reference")
    if not isinstance(reference, Mapping):
        raise ValueError("有状态离线缓存缺少 origin/request.json 中的 reference")

    url = normalize_reference_url(str(reference.get("url") or ""))
    _validate_reference_url(url)
    raw_headers = reference.get("request_headers")
    if not isinstance(raw_headers, Mapping):
        raw_headers = {}

    headers = _build_navigation_headers(raw_headers, reference_url=url)
    user_agent = _read_header(raw_headers, "user-agent") or headers.get("User-Agent", "")
    cookie_header = _read_header(raw_headers, "cookie")
    cookies = _parse_cookie_header(cookie_header)

    # User-Agent 由 Playwright context 参数设置，Cookie 由 add_cookies 写入，避免重复放入额外请求头。
    headers.pop("User-Agent", None)
    headers.pop("Cookie", None)
    return OfflineNavigationState(
        mode="stateful",
        url=url,
        user_agent=user_agent,
        headers=headers,
        cookies=cookies,
    )


def _resolve_request_json_path(
    *,
    article_directory: str | Path | None,
    request_json_path: str | Path | None,
) -> Path:
    if request_json_path:
        path = Path(request_json_path)
    elif article_directory:
        path = Path(article_directory) / "origin" / "request.json"
    else:
        raise ValueError("有状态离线缓存缺少文章目录")
    if not path.is_file():
        raise FileNotFoundError("有状态离线缓存未找到 origin/request.json")
    return path


def _load_evidence(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("origin/request.json 格式错误，无法启用有状态离线缓存") from exc
    if not isinstance(value, dict):
        raise ValueError("origin/request.json 内容不是对象，无法启用有状态离线缓存")
    return value


def _validate_reference_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https":
        raise ValueError("有状态离线缓存 reference URL 必须使用 HTTPS")
    if (parsed.hostname or "").lower() != WECHAT_ARTICLE_HOST:
        raise ValueError("有状态离线缓存 reference URL 不是微信文章域名")
    if parsed.path.rstrip("/") != WECHAT_ARTICLE_PATH:
        raise ValueError("有状态离线缓存 reference URL 不是微信文章主请求")


def _build_navigation_headers(
    raw_headers: Mapping[str, Any],
    *,
    reference_url: str,
) -> dict[str, str]:
    replay_headers = {
        str(key).strip().lower(): str(value).strip()
        for key, value in raw_headers.items()
        if str(key).strip()
        and str(value).strip()
        and "\r" not in str(value)
        and "\n" not in str(value)
    }
    return build_wechat_article_document_headers(reference_url, replay_headers)


def _read_header(headers: Mapping[str, Any], name: str) -> str:
    wanted = name.lower()
    for raw_key, raw_value in headers.items():
        if str(raw_key).strip().lower() == wanted:
            return str(raw_value).strip()
    return ""


def _parse_cookie_header(cookie_header: str) -> tuple[dict[str, Any], ...]:
    if not cookie_header.strip():
        return ()
    parsed = SimpleCookie()
    try:
        parsed.load(cookie_header)
        values = tuple(
            {
                "name": str(name),
                "value": str(morsel.value),
                "url": "https://mp.weixin.qq.com/",
            }
            for name, morsel in parsed.items()
            if str(name).strip()
        )
        if values:
            return values
    except Exception:
        pass

    # Cookie 中存在不规范片段时，退回到最小可用解析，仍避免把原始 Cookie 写入日志。
    cookies: list[dict[str, Any]] = []
    for part in cookie_header.split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            continue
        cookies.append({"name": name, "value": value, "url": "https://mp.weixin.qq.com/"})
    return tuple(cookies)


__all__ = ["OfflineNavigationState", "load_offline_navigation_state"]
