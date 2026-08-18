from __future__ import annotations

from html import escape as escape_html
from html import unescape as unescape_html
import re
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlparse


RESOURCE_HINT_RELS = {"preconnect", "dns-prefetch", "prefetch", "preload"}
RESOURCE_ATTRIBUTES = (
    "src",
    "href",
    "poster",
    "data-src",
    "data-original",
    "data-original-src",
    "data-lazy-src",
    "data-actualsrc",
    "data-before-oversubscription-url",
    "data-url",
    "data-headimgurl",
    "data-authiconurl",
    "data-coverurl",
    "data-cover",
    "data-thumburl",
    "data-poster",
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
SCRIPT_OR_NOSCRIPT_PATTERN = re.compile(
    r"<(?P<tag>script|noscript)\b[^>]*>.*?</(?P=tag)\s*>",
    re.IGNORECASE | re.DOTALL,
)
LINK_TAG_PATTERN = re.compile(r"<link\b[^>]*>", re.IGNORECASE | re.DOTALL)
OPEN_TAG_PATTERN = re.compile(
    r"<(?P<tag>[a-zA-Z][a-zA-Z0-9_:\.-]*)(?P<attrs>[^>]*)>",
    re.IGNORECASE | re.DOTALL,
)
MEDIA_OPEN_TAG_PATTERN = re.compile(
    r"<(?P<tag>video|audio)\b(?P<attrs>[^>]*)>",
    re.IGNORECASE | re.DOTALL,
)
WECHAT_VIDEOSNAP_PATTERN = re.compile(
    r"(?P<open><mp-common-videosnap\b(?P<attrs>[^>]*)>)"
    r"(?P<body>.*?)"
    r"(?P<close></mp-common-videosnap\s*>)",
    re.IGNORECASE | re.DOTALL,
)
WECHAT_VIDEO_IFRAME_PATTERN = re.compile(
    r"<iframe\b(?P<attrs>[^>]*)>\s*</iframe\s*>",
    re.IGNORECASE | re.DOTALL,
)
VIDEO_ELEMENT_PATTERN = re.compile(
    r"(?P<open><video\b(?P<attrs>[^>]*)>)(?P<body>.*?)(?P<close></video\s*>)",
    re.IGNORECASE | re.DOTALL,
)
SOURCE_OPEN_TAG_PATTERN = re.compile(r"<source\b[^>]*>", re.IGNORECASE | re.DOTALL)
STYLE_TAG_PATTERN = re.compile(
    r"(?P<open><style\b[^>]*>)(?P<body>.*?)(?P<close></style\s*>)",
    re.IGNORECASE | re.DOTALL,
)
REL_ATTRIBUTE_PATTERN = re.compile(
    r"\brel\s*=\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote)|"
    r"\brel\s*=\s*(?P<bare>[^\s>]+)",
    re.IGNORECASE | re.DOTALL,
)
HTML_ATTRIBUTE_READ_PATTERN_TEMPLATE = (
    r"\b{name}\s*=\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote)|"
    r"\b{name}\s*=\s*(?P<bare>[^\s>]+)"
)
WECHAT_MEDIA_OVERLAY_CLASS_TOKENS = {
    "video_mask",
    "video_length",
    "pic_mid_play",
    "poster_cover",
    "wx_video_play_opr",
    "video_poster__info__play",
    "video_poster__info__mask",
}
MEDIA_ATTRIBUTES_TO_REMOVE = (
    "crossorigin",
    "controlslist",
    "playsinline",
    "webkit-playsinline",
    "x5-playsinline",
    "x5-video-player-type",
    "x5-video-player-fullscreen",
    "x5-video-orientation",
)
OFFLINE_MEDIA_PLAYBACK_SCRIPT = """<script data-awa-offline-media-toggle="1">
(() => {
  const toggleMedia = (media) => {
    if (!media) {
      return;
    }
    if (!media.paused) {
      media.pause();
      return;
    }
    const playResult = media.play();
    if (playResult && typeof playResult.catch === 'function') {
      playResult.catch(() => {});
    }
  };
  document.addEventListener('click', (event) => {
    const target = event.target;
    if (!target || typeof target.closest !== 'function') {
      return;
    }
    const media = target.closest('video,audio');
    if (!media) {
      return;
    }
    toggleMedia(media);
  });
})();
</script>"""


def rewrite_html_resource_links(
    html_text: str,
    resource_map: dict[str, str],
    *,
    base_url: str,
) -> str:
    sanitized_html = _remove_script_blocks(html_text)
    sanitized_html = _remove_resource_hint_links(sanitized_html)
    sanitized_html = _rewrite_style_tag_resource_links(
        sanitized_html,
        resource_map,
        base_url=base_url,
    )

    def replace_attribute(match: re.Match[str]) -> str:
        name = match.group("name").lower()
        value = match.group("value")
        quote = match.group("quote")
        prefix = match.group("prefix")
        # 离线文件不能继续执行原页联网脚本，但普通 a.href 真实链接要保留。
        if name.startswith("on"):
            return ""
        if name in RESOURCE_ATTRIBUTES:
            value = _rewrite_url(value, resource_map, base_url)
        elif name == "srcset":
            value = _rewrite_srcset(value, resource_map, base_url)
        elif name == "style":
            value = rewrite_css_resource_links(value, resource_map, base_url=base_url)
        return f"{prefix}{quote}{value}{quote}"

    rewritten_html = ATTRIBUTE_PATTERN.sub(replace_attribute, sanitized_html)
    rewritten_html = _convert_wechat_video_iframes_to_offline_media(
        rewritten_html,
        resource_map,
    )
    rewritten_html = _convert_wechat_videosnap_to_native_video(rewritten_html)
    rewritten_html = _enable_native_media_controls(rewritten_html)
    rewritten_html = _hide_wechat_video_iframe_placeholders(rewritten_html)
    rewritten_html = _hide_wechat_media_overlays(rewritten_html)
    rewritten_html = _normalize_video_source_markup(rewritten_html)
    return _inject_offline_media_playback_handler(rewritten_html)


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


def _remove_script_blocks(html_text: str) -> str:
    return SCRIPT_OR_NOSCRIPT_PATTERN.sub("", html_text)


def _remove_resource_hint_links(html_text: str) -> str:
    def replace_link(match: re.Match[str]) -> str:
        rel_value = _read_rel_attribute(match.group(0))
        rel_tokens = {item.strip().lower() for item in rel_value.split() if item.strip()}
        if rel_tokens & RESOURCE_HINT_RELS:
            return ""
        return match.group(0)

    return LINK_TAG_PATTERN.sub(replace_link, html_text)


def _rewrite_style_tag_resource_links(
    html_text: str,
    resource_map: dict[str, str],
    *,
    base_url: str,
) -> str:
    def replace_style(match: re.Match[str]) -> str:
        rewritten_body = rewrite_css_resource_links(
            match.group("body"),
            resource_map,
            base_url=base_url,
        )
        return f"{match.group('open')}{rewritten_body}{match.group('close')}"

    return STYLE_TAG_PATTERN.sub(replace_style, html_text)


def _read_rel_attribute(link_tag: str) -> str:
    match = REL_ATTRIBUTE_PATTERN.search(link_tag)
    if match is None:
        return ""
    return str(match.group("value") or match.group("bare") or "")


def _enable_native_media_controls(html_text: str) -> str:
    """原微信播放器脚本会被离线清理，所以视频音频必须启用浏览器原生控件。"""

    def replace_media_tag(match: re.Match[str]) -> str:
        opening_tag = match.group(0)
        for attribute in MEDIA_ATTRIBUTES_TO_REMOVE:
            opening_tag = _remove_html_attribute(opening_tag, attribute)
        attrs = match.group("attrs")
        if _has_exact_attribute(attrs, "controls"):
            return opening_tag
        return f"{opening_tag[:-1]} controls>"

    return MEDIA_OPEN_TAG_PATTERN.sub(replace_media_tag, html_text)


def _hide_wechat_media_overlays(html_text: str) -> str:
    """隐藏依赖微信脚本的播放遮罩，避免挡住原生 video/audio 控件。"""

    def replace_open_tag(match: re.Match[str]) -> str:
        opening_tag = match.group(0)
        attrs = match.group("attrs")
        class_tokens = set(_read_html_attribute(attrs, "class").split())
        if not (class_tokens & WECHAT_MEDIA_OVERLAY_CLASS_TOKENS):
            return opening_tag
        return _append_inline_style(
            opening_tag,
            "display:none !important;pointer-events:none !important;",
        )

    return OPEN_TAG_PATTERN.sub(replace_open_tag, html_text)


def _normalize_video_source_markup(html_text: str) -> str:
    """把 video.src 改成标准 source 子节点，让浏览器按明确 MIME 类型加载。"""

    def replace_video(match: re.Match[str]) -> str:
        opening_tag = match.group("open")
        attrs = match.group("attrs")
        body = match.group("body")
        close_tag = match.group("close")
        source_url = _read_html_attribute(attrs, "src")
        if not source_url:
            return match.group(0)

        opening_tag = _remove_html_attribute(opening_tag, "src")
        source_tag = (
            f'<source src="{escape_html(source_url, quote=True)}" '
            f'type="{_video_mime_type(source_url)}">'
        )
        if not _body_has_source_for_url(body, source_url):
            body = f"\n  {source_tag}{body}"
        if "data-awa-video-fallback" not in body:
            body = (
                f"{body}\n  <p data-awa-video-fallback=\"1\">"
                f"当前浏览器不支持 HTML5 视频。"
                f'<a href="{escape_html(source_url, quote=True)}">打开视频文件</a>'
                f"</p>\n"
            )
        return f"{opening_tag}{body}{close_tag}"

    return VIDEO_ELEMENT_PATTERN.sub(replace_video, html_text)


def _convert_wechat_videosnap_to_native_video(html_text: str) -> str:
    """将微信视频号自定义组件转换为静态封面区域；视频号本体暂不离线下载。"""

    def replace_videosnap(match: re.Match[str]) -> str:
        attrs = match.group("attrs")
        cover_url = (
            _read_html_attribute(attrs, "data-coverurl")
            or _read_html_attribute(attrs, "data-cover")
            or _read_html_attribute(attrs, "data-thumburl")
            or _read_html_attribute(attrs, "data-poster")
            or _read_html_attribute(attrs, "data-url")
        )
        if not cover_url:
            return match.group(0)
        width = _read_html_attribute(attrs, "data-width")
        height = _read_html_attribute(attrs, "data-height")
        wrapper_style = "max-width:100%;margin:1em 0;"
        context_style = (
            f"background-image:url('{escape_html(cover_url, quote=True)}');"
            "background-position:center;background-repeat:no-repeat;"
            "background-size:cover;position:relative;width:100%;"
        )
        if width.isdigit() and height.isdigit() and int(width) > 0 and int(height) > 0:
            context_style += f"aspect-ratio:{width}/{height};"
        else:
            context_style += "min-height:240px;"
        return (
            f'<div class="awa-offline-videosnap" style="{wrapper_style}">'
            f'<div class="wxw_wechannel_video_context" style="{context_style}">'
            '<i class="weui-play-btn_primary"></i>'
            "</div></div>"
        )

    return WECHAT_VIDEOSNAP_PATTERN.sub(replace_videosnap, html_text)


def _convert_wechat_video_iframes_to_offline_media(
    html_text: str,
    resource_map: dict[str, str],
) -> str:
    """将普通微信视频 iframe 转为离线可见的原生视频；无 MP4 时显示封面。"""

    def replace_iframe(match: re.Match[str]) -> str:
        attrs = match.group("attrs")
        if not _is_wechat_video_iframe(attrs):
            return match.group(0)

        cover_url = _decode_resource_attribute_url(
            _read_html_attribute(attrs, "data-cover")
            or _read_html_attribute(attrs, "data-coverurl")
            or _read_html_attribute(attrs, "data-poster")
        )
        video_path = _select_local_video_path(resource_map)
        style = _offline_video_style(attrs)
        if video_path:
            poster_attr = (
                f' poster="{escape_html(cover_url, quote=True)}"' if cover_url else ""
            )
            escaped_video_path = escape_html(video_path, quote=True)
            return (
                f'<video class="awa-offline-video" controls{poster_attr} style="{style}">'
                f'\n  <source src="{escaped_video_path}" type="{_video_mime_type(video_path)}">'
                "\n  <p data-awa-video-fallback=\"1\">"
                "当前浏览器不支持 HTML5 视频。"
                f'<a href="{escaped_video_path}">打开视频文件</a>'
                "</p>\n</video>"
            )

        if cover_url:
            escaped_cover = escape_html(cover_url, quote=True)
            return (
                f'<div class="awa-offline-video-placeholder" style="{style}'
                'position:relative;background:#000;overflow:hidden;">'
                f'<img src="{escaped_cover}" alt="视频封面" '
                'style="display:block;width:100%;height:100%;object-fit:cover;">'
                '<span class="weui-play-btn_primary" aria-hidden="true"></span>'
                "</div>"
            )
        return match.group(0)

    return WECHAT_VIDEO_IFRAME_PATTERN.sub(replace_iframe, html_text)


def _is_wechat_video_iframe(attrs: str) -> bool:
    class_tokens = set(_read_html_attribute(attrs, "class").split())
    if "video_iframe" in class_tokens:
        return True
    return bool(_read_html_attribute(attrs, "data-mpvid"))


def _decode_resource_attribute_url(value: str) -> str:
    text = unescape_html(str(value or "").strip())
    if "%" in text and not urlparse(text).scheme:
        text = unquote(text)
    return text


def _select_local_video_path(resource_map: dict[str, str]) -> str:
    for local_path in resource_map.values():
        text = str(local_path or "")
        if text.startswith("assets/video/"):
            return text
    return ""


def _offline_video_style(attrs: str) -> str:
    style = "display:block;width:100%;max-width:100%;height:auto;"
    ratio = _read_html_attribute(attrs, "data-ratio")
    try:
        parsed_ratio = float(ratio)
    except (TypeError, ValueError):
        parsed_ratio = 0.0
    if parsed_ratio > 0:
        style += f"aspect-ratio:1/{parsed_ratio};"
    return style


def _hide_wechat_video_iframe_placeholders(html_text: str) -> str:
    """隐藏依赖微信脚本替换的视频 loading 占位，避免挡住离线封面或原生视频。"""

    def replace_open_tag(match: re.Match[str]) -> str:
        opening_tag = match.group(0)
        if match.group("tag").lower() != "span":
            return opening_tag
        attrs = match.group("attrs")
        class_tokens = set(_read_html_attribute(attrs, "class").split())
        if "js_img_placeholder" not in class_tokens:
            return opening_tag
        if not _read_html_attribute(attrs, "data-vid"):
            return opening_tag
        return _append_inline_style(
            opening_tag,
            "display:none !important;pointer-events:none !important;",
        )

    return OPEN_TAG_PATTERN.sub(replace_open_tag, html_text)


def _body_has_source_for_url(body: str, source_url: str) -> bool:
    for match in SOURCE_OPEN_TAG_PATTERN.finditer(body):
        if _read_html_attribute(match.group(0), "src") == source_url:
            return True
    return False


def _video_mime_type(source_url: str) -> str:
    path = urlparse(source_url).path.lower()
    if path.endswith(".webm"):
        return "video/webm"
    if path.endswith(".ogg") or path.endswith(".ogv"):
        return "video/ogg"
    return "video/mp4"


def _inject_offline_media_playback_handler(html_text: str) -> str:
    """离线页没有微信播放器脚本时，点击视频区域也能切换播放/暂停。"""
    if not MEDIA_OPEN_TAG_PATTERN.search(html_text):
        return html_text
    if 'data-awa-offline-media-toggle="1"' in html_text:
        return html_text
    body_close_pattern = re.compile(r"</body\s*>", re.IGNORECASE)
    if body_close_pattern.search(html_text):
        return body_close_pattern.sub(
            f"{OFFLINE_MEDIA_PLAYBACK_SCRIPT}</body>",
            html_text,
            count=1,
        )
    return f"{html_text}{OFFLINE_MEDIA_PLAYBACK_SCRIPT}"


def _append_inline_style(opening_tag: str, style_fragment: str) -> str:
    style_pattern = re.compile(
        HTML_ATTRIBUTE_READ_PATTERN_TEMPLATE.format(name=re.escape("style")),
        re.IGNORECASE | re.DOTALL,
    )
    match = style_pattern.search(opening_tag)
    if match is None:
        return f'{opening_tag[:-1]} style="{style_fragment}">'
    current_style = str(match.group("value") or match.group("bare") or "").strip()
    quote = match.group("quote") or '"'
    separator = "" if not current_style or current_style.endswith(";") else ";"
    replacement = f"style={quote}{current_style}{separator}{style_fragment}{quote}"
    return style_pattern.sub(replacement, opening_tag, count=1)


def _remove_html_attribute(opening_tag: str, name: str) -> str:
    pattern = re.compile(
        rf"\s+\b{re.escape(name)}\b(?:\s*=\s*(?P<quote>['\"]).*?(?P=quote)|\s*=\s*[^\s>]+)?",
        re.IGNORECASE | re.DOTALL,
    )
    return pattern.sub("", opening_tag)


def _read_html_attribute(attrs: str, name: str) -> str:
    pattern = re.compile(
        HTML_ATTRIBUTE_READ_PATTERN_TEMPLATE.format(name=re.escape(name)),
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(attrs)
    if match is None:
        return ""
    return str(match.group("value") or match.group("bare") or "")


def _has_exact_attribute(attrs: str, name: str) -> bool:
    return bool(
        re.search(
            rf"(?:^|\s){re.escape(name)}(?:\s|=|/|$)",
            attrs,
            re.IGNORECASE,
        )
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
    decoded = unescape_html(raw)
    percent_decoded = (
        unquote(decoded) if "%" in decoded and not urlparse(decoded).scheme else decoded
    )
    normalized = (
        f"https:{percent_decoded}" if percent_decoded.startswith("//") else percent_decoded
    )
    absolute = urljoin(base_url, normalized)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"}:
        return value
    for candidate in _resource_lookup_candidates(
        value,
        raw,
        decoded,
        percent_decoded,
        normalized,
        absolute,
    ):
        if candidate in resource_map:
            return resource_map[candidate]
    lookup_key = _wechat_image_lookup_key(absolute)
    if lookup_key:
        for source_url, local_path in resource_map.items():
            if _wechat_image_lookup_key(source_url) == lookup_key:
                return local_path
    return value


def _resource_lookup_candidates(*values: str) -> tuple[str, ...]:
    candidates: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        candidates.append(text)
        parsed = urlparse(text)
        if parsed.scheme in {"http", "https"} and parsed.fragment:
            without_fragment = parsed._replace(fragment="").geturl()
            if without_fragment and without_fragment not in seen:
                seen.add(without_fragment)
                candidates.append(without_fragment)
    return tuple(candidates)


def _wechat_image_lookup_key(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return ""
    host = parsed.netloc.lower()
    if not (host == "mmbiz.qpic.cn" or host.endswith(".mmbiz.qpic.cn")):
        return ""
    # 微信图片常追加 wxfrom、fragment 等展示参数；同一路径和格式可视为同一正文图片。
    wx_fmt = ""
    for key, item_value in parse_qsl(parsed.query, keep_blank_values=True):
        if key == "wx_fmt":
            wx_fmt = item_value
            break
    query = urlencode({"wx_fmt": wx_fmt}) if wx_fmt else ""
    return parsed._replace(query=query, fragment="").geturl()


__all__ = ["rewrite_css_resource_links", "rewrite_html_resource_links"]
