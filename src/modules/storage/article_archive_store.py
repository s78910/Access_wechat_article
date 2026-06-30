from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse, urlunparse

from src.core.progress_logger import ProgressLogger
from src.modules.detail.article_detail import (
    ArticleDetailFetchError,
    build_article_detail_from_html,
    fetch_article_detail_from_keyed_url,
    write_article_detail_json,
)
from src.modules.detail.account_identity import (
    ACCOUNT_NAME_PLACEHOLDER_MARKERS,
    first_valid_account_name as resolve_first_valid_account_name,
)
from src.modules.detail.comment_detail import CommentFetchError, fetch_comments_to_archive
from src.modules.storage.path_builder import build_article_archive_dir
from src.modules.utils.file_utils import clean_path_part
from src.modules.utils.time_utils import format_datetime_for_dir, normalize_datetime_text
from src.modules.utils.url_utils import redact_url as _redact_url


DEFAULT_COMMENT_FETCH_OPTIONS = {
    # 评论正文和图片/表情属于归档证据；头像只保留 URL，避免大量低价值图片拖慢主流程。
    "download_resources": True,
    "download_avatars": False,
    "download_emojis": True,
    "download_pictures": True,
    "resource_timeout_seconds": 5,
    "page_pause_seconds": 0,
    "reply_page_pause_seconds": 0,
}


class ArticleArchiveError(RuntimeError):
    """单篇文章本地归档失败，向上抛出可展示给用户的业务原因。"""


def first_non_empty(*values: Any) -> Any:
    """返回第一个非空值；数字 0 是有效业务值，不能当成缺失。"""
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def build_sqlite_capture_record(
    report: dict[str, Any],
    *,
    article_index: int,
    selections: dict[str, bool],
) -> dict[str, Any]:
    """从旧流程报告中抽取当前项目数据库需要的索引字段。"""
    storage = report.get("storage") if isinstance(report.get("storage"), dict) else {}
    main_html_capture = report.get("main_html_capture") if isinstance(report.get("main_html_capture"), dict) else {}
    comments = report.get("comment_fetch") if isinstance(report.get("comment_fetch"), dict) else {}

    title = str(storage.get("title") or (report.get("target_article") or {}).get("title") or f"第 {article_index} 篇文章")
    account_name = first_valid_account_name(storage.get("account_name"))
    storage_dir = str(storage.get("storage_dir") or "")
    article_url_redacted = str(storage.get("article_url_redacted") or main_html_capture.get("url_redacted") or "")
    collect_time = str(report.get("created_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    ok = bool(storage_dir and not report.get("automation_error"))

    return {
        "account_name": account_name,
        "article_title": title,
        "article_index": max(1, int(article_index)),
        "collect_time": collect_time,
        "collect_status": "已保存" if ok else "保存失败",
        "storage_dir": storage_dir,
        "article_url_redacted": article_url_redacted,
        "report_path": str(report.get("report_path") or ""),
        "options": dict(selections),
        "metadata": {
            "conclusion": report.get("conclusion", ""),
            "comment_count": comments.get("comment_count", comments.get("comments_extract_count", 0)),
            "reply_count": comments.get("reply_count", comments.get("comments_reply_count", 0)),
            "storage": storage,
        },
    }

def build_local_article_archive(
    report: dict[str, Any],
    *,
    article_index: int,
    selections: dict[str, bool],
    storage_root: Path,
    progress_logger: ProgressLogger | None = None,
    detail_fetcher=None,
    comment_fetcher=None,
) -> dict[str, Any]:
    """整理单篇文章本地归档，并生成 article_detail.json 作为数据库入库来源。"""
    if not isinstance(progress_logger, ProgressLogger):
        progress_logger = ProgressLogger(sink=progress_logger) if callable(progress_logger) else ProgressLogger()
    storage = report.get("storage") if isinstance(report.get("storage"), dict) else {}
    main_capture = report.get("main_html_capture") if isinstance(report.get("main_html_capture"), dict) else {}
    collect_time = normalize_time_text(report.get("created_at"))
    keyed_url = str(main_capture.get("url") or "")
    if not keyed_url:
        raise ArticleArchiveError("缺少带 key 的文章 URL，已跳过 article_detail.json 生成和 SQLite 写入")

    source_html = load_captured_main_html(main_capture, report.get("article_detail") if isinstance(report.get("article_detail"), dict) else {})
    detail: dict[str, Any]
    if source_html.strip():
        progress_logger.info(
            "article_detail",
            "MITM 已捕获带 key 请求的 response HTML，优先直接解析文章详情",
            substep="parse_detail_from_mitm_html",
            progress=26,
            meta={"urlRedacted": str(main_capture.get("url_redacted") or _redact_url(keyed_url))},
        )
        try:
            detail = build_article_detail_from_html(source_html, keyed_url, collect_time=collect_time)
        except ArticleDetailFetchError as exc:
            raise ArticleArchiveError(str(exc)) from exc
    elif str(main_capture.get("source") or "") in {"mitm_referer_fallback", "mitm_keyed_url_fallback"}:
        progress_logger.info(
            "article_detail",
            "MITM 已发现带 key URL，正在使用原请求头执行 requests 保底获取",
            substep="fetch_detail_by_referer_keyed_url",
            progress=26,
            meta={
                "urlRedacted": str(main_capture.get("url_redacted") or _redact_url(keyed_url)),
                "carrierUrlRedacted": str(main_capture.get("carrier_url_redacted") or ""),
                "headerCount": len(dict(main_capture.get("request_headers") or {})),
            },
        )
        fetcher = detail_fetcher or fetch_article_detail_from_keyed_url
        try:
            detail = fetcher(
                keyed_url,
                request_headers=dict(main_capture.get("request_headers") or {}),
                collect_time=collect_time,
            )
        except TypeError:
            detail = fetcher(keyed_url)
        except ArticleDetailFetchError as exc:
            raise ArticleArchiveError(str(exc)) from exc
    else:
        raise ArticleArchiveError(
            "MITM 已看到带 key 的文章主请求 URL，但没有捕获到 response HTML；"
            "为避免重复请求 key URL，本轮不启用 requests 保底"
        )

    if not isinstance(detail, dict):
        raise ArticleArchiveError("文章详情获取结果不是有效 JSON 对象")
    if not source_html.strip() and str(detail.get("_source_html") or "").strip():
        # requests 保底拿到的完整 HTML 不写入 article_detail.json，只复用给后续评论接口提取 comment_id。
        source_html = str(detail.get("_source_html") or "")
    detail.pop("_source_html", None)
    validate_referer_fallback_detail_title(report, detail)

    # 成功采集时以文章详情页解析出的公众号名为准，窗口识别结果只作为详情缺失时的兜底。
    account_name = first_valid_account_name(detail.get("account_name"), storage.get("account_name"))
    article_title = str(first_non_empty(detail.get("article_title"), storage.get("title"), f"第 {article_index} 篇文章"))
    published_time = normalize_published_article_time(
        first_non_empty(detail.get("published_article_time"), storage.get("published_article_time"), report.get("created_at"))
    )
    captured_article_url = first_valid_wechat_article_short_link(detail.get("short_link"), storage.get("article_url"))
    if not captured_article_url:
        raise ArticleArchiveError(
            "未从文章详情响应中解析到短链接 https://mp.weixin.qq.com/s/xxxx，"
            "已跳过 article_detail.json 生成和 SQLite 写入"
        )

    detail["account_name"] = account_name
    detail["article_title"] = article_title
    detail["published_article_time"] = published_time
    detail["short_link"] = captured_article_url

    progress_logger.info(
        "local_archive",
        f"开始整理本地归档：{account_name} / {published_time} {article_title}",
        substep="archive_start",
        progress=30,
        meta={"articleLink": captured_article_url, "accountName": account_name, "articleTitle": article_title},
    )
    archive_dir = allocate_article_archive_dir(storage_root, account_name, published_time, article_title)
    progress_logger.info(
        "filesystem",
        f"已确定归档目录：{archive_dir}",
        substep="archive_dir_ready",
        progress=33,
        meta={"archiveDir": str(archive_dir)},
    )
    progress_logger.info(
        "article_detail",
        "正在生成 article_detail.json 结构化内容",
        substep="build_detail_json",
        progress=45,
        meta={"targetDir": str(archive_dir)},
    )
    detail_path = write_article_detail_json(detail, archive_dir)
    progress_logger.success(
        "article_detail",
        f"article_detail.json 已写入：{detail_path}",
        substep="detail_json_written",
        progress=90,
        meta={"target": str(detail_path)},
    )

    comment_fetch: dict[str, Any] = {"attempted": False, "reason": "comment_info_not_selected"}
    if bool(selections.get("commentInfo", False)):
        progress_logger.info(
            "comment_info",
            "文章详情已完成，开始请求评论信息接口",
            substep="comment_fetch_start",
            progress=91,
            meta={"targetDir": str(archive_dir), "urlRedacted": str(main_capture.get("url_redacted") or _redact_url(keyed_url))},
        )
        comment_runner = comment_fetcher or fetch_comments_to_archive
        try:
            comment_fetch = comment_runner(
                keyed_url,
                source_html,
                archive_dir,
                request_headers=dict(main_capture.get("request_headers") or {}),
                collect_time=collect_time,
                **DEFAULT_COMMENT_FETCH_OPTIONS,
            )
        except TypeError:
            comment_fetch = comment_runner(keyed_url, source_html, archive_dir)
        except CommentFetchError as exc:
            comment_fetch = {"attempted": True, "ok": False, "error": str(exc)}
        except Exception as exc:
            comment_fetch = {"attempted": True, "ok": False, "error": str(exc)}

        if comment_fetch.get("ok"):
            progress_logger.success(
                "comment_info",
                f"评论信息已写入：{comment_fetch.get('comments_final_json_path', '')}",
                substep="comment_fetch_done",
                progress=93,
                meta={
                    "commentCount": comment_fetch.get("comment_count", 0),
                    "replyCount": comment_fetch.get("reply_count", 0),
                    "resourceCounts": comment_fetch.get("comment_resource_counts", {}),
                },
            )
        else:
            progress_logger.warn(
                "comment_info",
                f"评论信息获取失败或无可返回数据：{comment_fetch.get('error') or comment_fetch.get('reason') or comment_fetch.get('stop_reason') or 'unknown'}",
                substep="comment_fetch_failed",
                progress=93,
                meta=comment_fetch,
            )

    archive = {
        "storage_dir": str(archive_dir),
        "article_detail_path": str(detail_path),
        "detail": detail,
        "comment_fetch": comment_fetch,
        "selections": dict(selections or {}),
    }
    report["storage"] = {
        **storage,
        "account_name": detail.get("account_name") or account_name,
        "title": detail.get("article_title") or article_title,
        "storage_dir": str(archive_dir),
        "article_url": detail.get("short_link") or captured_article_url,
        "article_url_redacted": detail.get("short_link") or captured_article_url,
    }
    report["article_detail"] = detail
    report["comment_fetch"] = comment_fetch
    progress_logger.success(
        "local_archive",
        f"本地归档完成：{archive_dir}",
        substep="archive_done",
        progress=92,
        meta={"archiveDir": str(archive_dir)},
    )
    return archive

def build_public_article_record(archive: dict[str, Any]) -> dict[str, Any]:
    detail = archive.get("detail") if isinstance(archive.get("detail"), dict) else {}
    selections = archive.get("selections") if isinstance(archive.get("selections"), dict) else {"articleDetail": True}
    article_link = normalize_wechat_article_short_link(detail.get("short_link") or detail.get("article_link"))
    if not article_link:
        raise ArticleArchiveError("SQLite 入库失败：article_link 缺少有效文章短链接")
    return {
        "account_name": first_valid_account_name(detail.get("account_name")),
        "article_title": detail.get("article_title") or "",
        "published_article_time": detail.get("published_article_time") or datetime.now().strftime("%Y-%m-%d %H:%M"),
        "article_link": article_link,
        "record_type": build_record_type_from_selections(selections),
        "collect_time": detail.get("collect_time") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "duration_seconds": float(detail.get("duration_seconds") or 0),
        "collect_status": "saved",
    }

def build_record_type_from_selections(selections: dict[str, bool] | None) -> str:
    """把前端采集选项转换成数据库 record_type 使用的中文名称。"""
    data = selections if isinstance(selections, dict) else {}
    items: list[str] = []
    if bool(data.get("articleDetail", True)):
        items.append("文章详情")
    if bool(data.get("commentInfo")):
        items.append("评论信息")
    return ", ".join(items) or "文章详情"

def build_failed_public_article_record(
    report: dict[str, Any],
    *,
    article_index: int,
    selections: dict[str, bool] | None = None,
    account_name: str = "",
    target_title: str = "",
    failure_reason: str = "",
    duration_seconds: float = 0.0,
) -> dict[str, Any]:
    """把可识别标题的失败记录写入索引；未知标题或公众号直接跳过落库。"""
    storage = report.get("storage") if isinstance(report.get("storage"), dict) else {}
    target_article = report.get("target_article") if isinstance(report.get("target_article"), dict) else {}
    title = str(
        first_non_empty(
            target_title,
            target_article.get("title"),
            storage.get("title"),
            f"第 {max(1, int(article_index))} 篇文章",
        )
    ).strip()
    collect_time = normalize_time_text(report.get("created_at"))
    resolved_account_name = first_valid_account_name(account_name, storage.get("account_name"))
    if resolved_account_name == "未知公众号":
        raise ArticleArchiveError("主页公众号名称未识别，失败记录不写入 SQLite")
    if not is_recognized_article_title(title):
        raise ArticleArchiveError("主页文章标题未识别，失败记录不写入 SQLite")
    return {
        "account_name": resolved_account_name,
        "article_title": title,
        "published_article_time": "",
        "article_link": "",
        "record_type": build_record_type_from_selections(selections),
        "collect_time": collect_time,
        "duration_seconds": max(0.0, float(duration_seconds or 0.0)),
        "collect_status": "failed",
    }

def validate_referer_fallback_detail_title(report: dict[str, Any], detail: dict[str, Any]) -> None:
    main_capture = report.get("main_html_capture") if isinstance(report.get("main_html_capture"), dict) else {}
    if str(main_capture.get("source") or "") not in {"mitm_referer_fallback", "mitm_keyed_url_fallback"}:
        return
    target_article = report.get("target_article") if isinstance(report.get("target_article"), dict) else {}
    storage = report.get("storage") if isinstance(report.get("storage"), dict) else {}
    expected = first_non_empty(target_article.get("title"), storage.get("title"))
    expected_title = normalize_compare_title(expected)
    actual_title = normalize_compare_title(detail.get("article_title"))
    if not expected_title or not actual_title:
        return
    if expected_title != actual_title:
        raise ArticleArchiveError(
            f"key URL 获取到的文章标题与主页标题不一致：主页标题={str(expected or '').strip()}，详情标题={str(detail.get('article_title') or '').strip()}"
        )

def normalize_compare_title(value: Any) -> str:
    text = str(value or "").replace("\u200b", "").strip().lower()
    return re.sub(r"\s+", "", text)

def load_captured_main_html(main_capture: dict[str, Any], raw_detail: dict[str, Any]) -> str:
    """优先读取 MITM 保存的 response HTML，兜底使用事件里携带的 html_text。"""
    source_html_path = Path(str(main_capture.get("private_html_path") or ""))
    if source_html_path.is_file():
        try:
            return source_html_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            pass
    return str(raw_detail.get("html_text") or "")

def normalize_wechat_article_short_link(value: Any) -> str:
    """只接受 https://mp.weixin.qq.com/s/xxxx 形式的文章短链接。"""
    text = normalize_article_url_text(value)
    if not text:
        return ""
    parsed = urlparse(text)
    if (parsed.scheme or "").lower() != "https":
        return ""
    if (parsed.hostname or "").lower() != "mp.weixin.qq.com":
        return ""
    path = parsed.path.rstrip("/")
    if not path.startswith("/s/"):
        return ""
    slug = path.removeprefix("/s/").strip("/")
    if not slug:
        return ""
    return urlunparse(("https", "mp.weixin.qq.com", f"/s/{slug}", "", "", ""))

def first_valid_wechat_article_short_link(*values: Any) -> str:
    """按顺序返回第一个真正的微信文章短链接。"""
    for value in values:
        short_link = normalize_wechat_article_short_link(value)
        if short_link:
            return short_link
    return ""

def normalize_article_url_text(value: Any) -> str:
    text = html.unescape(str(value or "")).strip().strip("'\"")
    return text.replace("\\/", "/").replace("\\x26", "&").replace("\\u0026", "&")

def extract_wechat_short_link_from_html(html_text: str) -> str:
    """从 original_main.html 中寻找真正短链；不把带 key 的 /s?__biz 链接当短链。"""
    text = str(html_text or "")
    patterns = (
        r"(?:window\.)?short_link\s*=\s*['\"](?P<value>.*?)['\"]",
        r"var\s+msg_link\s*=\s*['\"](?P<value>.*?)['\"]",
        r"(?i)<meta[^>]+property=['\"]og:url['\"][^>]+content=['\"](?P<value>.*?)['\"]",
        r"(?i)<link[^>]+rel=['\"]canonical['\"][^>]+href=['\"](?P<value>.*?)['\"]",
        r"https://mp\.weixin\.qq\.com/s/[A-Za-z0-9_\-]+",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        candidate = match.group("value") if "value" in match.groupdict() else match.group(0)
        short_link = normalize_wechat_article_short_link(candidate)
        if short_link:
            return short_link
    return ""

def extract_article_detail_stats_from_html(html_text: str) -> dict[str, Any]:
    """尽量从主 HTML 里的 JS 变量提取详情；不存在的值保持 None。"""
    text = str(html_text or "")
    return {
        "ip": extract_article_ip_from_html(text),
        "audience_count": extract_first_numeric_html_value(text, ("tts_heard_person_cnt", "audience_count", "ori_read_num")),
        "read_count": extract_first_numeric_html_value(text, ("read_num", "read_num_new", "real_read_num")),
        "like_count": extract_first_numeric_html_value(text, ("old_like_num", "old_like_count")),
        "share_count": extract_first_numeric_html_value(text, ("share_num", "share_count")),
        "recommend_count": extract_first_numeric_html_value(text, ("like_count", "like_num", "recommend_count")),
        "comment_count": extract_first_numeric_html_value(text, ("comment_count", "elected_comment_total_cnt")),
    }

def extract_article_ip_from_html(html_text: str) -> str | None:
    """提取文章发布地；只接受明确发布地字段，避免把 show_ip_wording=1 误当成 IP。"""
    patterns = (
        r"\bprovinceName\b\s*[:=]\s*['\"](?P<value>[^'\"]+)['\"]",
        r"\bprovince_name\b\s*[:=]\s*['\"](?P<value>[^'\"]+)['\"]",
        r"\bcountryName\b\s*[:=]\s*['\"](?P<value>[^'\"]+)['\"]",
        r"\bcountry_name\b\s*[:=]\s*['\"](?P<value>[^'\"]+)['\"]",
        r"\bip_wording\b\s*[:=]\s*['\"](?P<value>[^'\"]+)['\"]",
    )
    for pattern in patterns:
        match = re.search(pattern, html_text)
        if not match:
            continue
        value = re.sub(r"\s+", "", html.unescape(match.group("value"))).strip()
        if is_valid_article_ip_wording(value):
            return value
    return None

def first_valid_account_name(*values: Any) -> str:
    """返回第一个真实公众号名；过滤窗口检测状态提示，避免污染目录和数据库。"""
    return resolve_first_valid_account_name(*values)

def is_recognized_article_title(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text and text != "未识别标题")

def is_valid_article_ip_wording(value: str) -> bool:
    """过滤开关值、数字和脚本片段，只保留发布地文本。"""
    text = str(value or "").strip()
    if not text:
        return False
    if re.fullmatch(r"\d+", text):
        return False
    if len(text) > 20:
        return False
    return bool(re.search(r"[\u4e00-\u9fff]", text))

def extract_first_numeric_html_value(html_text: str, names: tuple[str, ...]) -> int | None:
    for name in names:
        escaped_name = re.escape(name)
        patterns = (
            rf"[\"']{escaped_name}[\"']\s*:\s*[\"']?(?P<value>\d+)[\"']?(?:\s*\*\s*1)?",
            rf"\b{escaped_name}\b\s*:\s*[\"']?(?P<value>\d+)[\"']?(?:\s*\*\s*1)?",
            rf"\b{escaped_name}\b\s*=\s*[\"']?(?P<value>\d+)[\"']?(?:\s*\*\s*1)?",
        )
        for pattern in patterns:
            match = re.search(pattern, html_text)
            if match:
                return int(match.group("value"))
    return None

def build_article_stats(
    raw_detail: dict[str, Any],
    raw_metrics: dict[str, Any],
    comment_fetch: dict[str, Any],
    html_stats: dict[str, Any],
) -> dict[str, Any]:
    return {
        "audience_count": none_if_missing(
            first_non_empty(raw_detail.get("audience_count"), raw_metrics.get("audience_count"), html_stats.get("audience_count"))
        ),
        "read_count": none_if_missing(
            first_non_empty(
                raw_detail.get("read_count"),
                raw_metrics.get("read_num"),
                raw_metrics.get("read_num_new"),
                raw_metrics.get("real_read_num"),
                html_stats.get("read_count"),
            )
        ),
        "like_count": none_if_missing(
            first_non_empty(
                raw_detail.get("like_count"),
                raw_metrics.get("old_like_num"),
                raw_metrics.get("old_like_count"),
                html_stats.get("like_count"),
            )
        ),
        "share_count": none_if_missing(
            first_non_empty(raw_detail.get("share_count"), raw_metrics.get("share_num"), html_stats.get("share_count"))
        ),
        "recommend_count": none_if_missing(
            first_non_empty(
                raw_detail.get("recommend_count"),
                raw_metrics.get("like_num"),
                raw_metrics.get("recommend_count"),
                html_stats.get("recommend_count"),
            )
        ),
        "comment_count": none_if_missing(
            first_non_empty(
                raw_detail.get("comment_count"),
                raw_metrics.get("comment_count"),
                comment_fetch.get("comment_count"),
                comment_fetch.get("comments_extract_count"),
                html_stats.get("comment_count"),
            )
        ),
    }

def allocate_article_archive_dir(storage_root: Path, account_name: str, published_time: str, title: str) -> Path:
    candidate = build_article_archive_dir(
        storage_root=storage_root,
        account_name=account_name or "未知公众号",
        published_time=published_time,
        article_title=title or "无标题文章",
    )
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate

def sanitize_path_part(value: str, max_length: int = 120) -> str:
    return clean_path_part(value, max_length=max_length)

def format_time_for_dir(value: str) -> str:
    return format_datetime_for_dir(value)

def normalize_time_text(value: Any) -> str:
    return normalize_datetime_text(value)

def normalize_published_article_time(value: Any) -> str:
    """文章发布时间只按页面展示精度保存到分钟，避免写入实际不存在的秒。"""
    text = str(value or "").strip().replace("T", " ")
    if not text:
        return datetime.now().strftime("%Y-%m-%d %H:%M")
    if re.fullmatch(r"\d{8,}", text):
        try:
            return datetime.fromtimestamp(int(text)).strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError, OSError):
            return datetime.now().strftime("%Y-%m-%d %H:%M")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", text):
        return text
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}) (\d{2})-(\d{2})", text)
    if match:
        return f"{match.group(1)} {match.group(2)}:{match.group(3)}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}.*", text):
        return text[:16]
    return text

def build_original_request_summary(main_capture: dict[str, Any]) -> dict[str, Any]:
    context_path = Path(str(main_capture.get("request_context_file") or ""))
    request_context = _load_json_object(context_path)
    url = str(main_capture.get("url") or request_context.get("url") or request_context.get("request_url") or "")
    headers = request_context.get("request_headers") if isinstance(request_context.get("request_headers"), dict) else {}
    return {
        "method": str(request_context.get("method") or request_context.get("request_method") or "GET"),
        "url": url,
        "url_redacted": str(main_capture.get("url_redacted") or (_redact_url(url) if url else "")),
        "query": parse_qs(urlparse(url).query, keep_blank_values=True),
        "request_headers": headers,
        "request_context": request_context,
        "captured_time": normalize_time_text(main_capture.get("captured_time")),
        "status_code": main_capture.get("status_code"),
        "content_type": _header_value(main_capture.get("response_headers") or {}, "content-type"),
    }

def none_if_missing(value: Any) -> Any:
    return None if value in {"", None} else value

def infer_record_type(article_title: str, original_html_path: Path) -> str:
    if not str(article_title or "").strip():
        return "无标题文章"
    try:
        html_text = original_html_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "完整文章"
    body_text = re.sub(r"<[^>]+>", "", html_text)
    return "纯图文文章" if len(body_text.strip()) < 20 else "完整文章"

def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}

def _header_value(headers: dict[str, Any], name: str) -> str:
    target = name.lower()
    for key, value in dict(headers or {}).items():
        if str(key).lower() == target:
            return str(value)
    return ""


__all__ = [
    "ArticleArchiveError",
    "ArticleDetailFetchError",
    "CommentFetchError",
    "build_local_article_archive",
    "build_failed_public_article_record",
    "build_public_article_record",
    "build_sqlite_capture_record",
    "fetch_article_detail_from_keyed_url",
    "fetch_comments_to_archive",
    "extract_article_detail_stats_from_html",
    "extract_article_ip_from_html",
    "normalize_wechat_article_short_link",
]
