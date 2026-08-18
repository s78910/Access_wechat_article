from __future__ import annotations

import hashlib
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable, Mapping, Sequence
from urllib.parse import urlparse

import requests


CONTENT_RANGE_PATTERN = re.compile(
    r"^bytes\s+(?P<start>\d+)-(?P<end>\d+)/(?P<total>\d+|\*)$",
    re.IGNORECASE,
)
FORWARDED_REQUEST_HEADERS = {
    "accept",
    "accept-language",
    "referer",
    "user-agent",
}
MEDIA_CONTENT_TYPE_EXTENSIONS = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
}
STREAM_CHUNK_SIZE = 256 * 1024


class _MediaDownloadError(RuntimeError):
    """仅用于承载不包含 URL、Cookie 等敏感信息的内部校验原因。"""


@dataclass(frozen=True, slots=True)
class MediaCandidate:
    url: str
    content_type: str
    request_headers: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class MediaDownloadResult:
    ok: bool
    source_url: str
    content_type: str
    local_path: Path | None = None
    relative_path: str = ""
    bytes_downloaded: int = 0
    message: str = ""


class RequestsMediaDownloader:
    """使用 Playwright 会话信息下载单个完整媒体文件。"""

    def __init__(
        self,
        assets_dir: str | Path,
        *,
        timeout_seconds: float,
        session_factory: Callable[[], requests.Session] = requests.Session,
    ) -> None:
        self.assets_dir = Path(assets_dir)
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self.session_factory = session_factory

    def download(
        self,
        candidate: MediaCandidate,
        *,
        cookies: Sequence[Mapping[str, object]],
    ) -> MediaDownloadResult:
        source_url = str(candidate.url or "").strip()
        content_type = _normalize_content_type(candidate.content_type)
        if _is_m3u8(source_url, content_type):
            return _failure(source_url, content_type, "暂不支持 m3u8/HLS 媒体归档")
        if not _is_http_url(source_url):
            return _failure(source_url, content_type, "媒体地址不是有效的 HTTP URL")

        target_path = _build_target_path(self.assets_dir, source_url, content_type)
        part_path = target_path.with_suffix(f"{target_path.suffix}.part")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        part_path.unlink(missing_ok=True)

        session = self.session_factory()
        response = None
        try:
            _apply_cookies(session, cookies)
            base_headers = _filtered_request_headers(candidate.request_headers)
            downloaded = 0
            expected_total: int | None = None

            while True:
                request_headers = dict(base_headers)
                if downloaded:
                    request_headers["Range"] = f"bytes={downloaded}-"
                response = session.get(
                    source_url,
                    headers=request_headers,
                    stream=True,
                    timeout=self.timeout_seconds,
                    allow_redirects=True,
                )
                status_code = int(getattr(response, "status_code", 0) or 0)
                response_headers = _normalized_headers(getattr(response, "headers", {}))
                response_content_type = _normalize_content_type(
                    response_headers.get("content-type", "")
                )
                if response_content_type:
                    content_type = response_content_type

                if status_code == 200:
                    if downloaded:
                        raise _MediaDownloadError("续传请求返回完整响应，无法保证字节连续")
                    written = _write_response_body(response, part_path, append=False)
                    declared_length = _positive_int(response_headers.get("content-length"))
                    if declared_length is not None and written != declared_length:
                        raise _MediaDownloadError("媒体响应长度与 Content-Length 不一致")
                    downloaded = written
                    break

                if status_code != 206:
                    raise _MediaDownloadError(f"媒体请求返回 HTTP {status_code}")

                byte_range = _parse_content_range(response_headers.get("content-range", ""))
                if byte_range is None:
                    raise _MediaDownloadError("206 响应缺少有效 Content-Range")
                range_start, range_end, range_total = byte_range
                if range_start != downloaded:
                    raise _MediaDownloadError("媒体分段起点不连续")
                if expected_total is not None and range_total != expected_total:
                    raise _MediaDownloadError("媒体分段总长度发生变化")
                expected_total = range_total

                written = _write_response_body(response, part_path, append=downloaded > 0)
                expected_segment_size = range_end - range_start + 1
                if written != expected_segment_size:
                    raise _MediaDownloadError("媒体分段长度与 Content-Range 不一致")
                downloaded += written
                if downloaded == expected_total:
                    break
                if downloaded > expected_total:
                    raise _MediaDownloadError("媒体分段写入长度超过总长度")
                response.close()
                response = None

            if downloaded <= 0:
                raise _MediaDownloadError("媒体响应内容为空")
            os.replace(part_path, target_path)
            return MediaDownloadResult(
                ok=True,
                source_url=source_url,
                content_type=content_type,
                local_path=target_path,
                relative_path=f"{self.assets_dir.name}/{target_path.parent.name}/{target_path.name}",
                bytes_downloaded=downloaded,
                message="媒体下载完成",
            )
        except Exception as exc:
            part_path.unlink(missing_ok=True)
            detail = str(exc) if isinstance(exc, _MediaDownloadError) else type(exc).__name__
            return _failure(
                source_url,
                content_type,
                f"媒体下载失败：{detail}",
            )
        finally:
            if response is not None:
                response.close()
            session.close()


def download_media_candidate(
    candidate: MediaCandidate,
    assets_dir: str | Path,
    *,
    cookies: Sequence[Mapping[str, object]],
    timeout_seconds: float,
    session_factory: Callable[[], requests.Session] = requests.Session,
) -> MediaDownloadResult:
    return RequestsMediaDownloader(
        assets_dir,
        timeout_seconds=timeout_seconds,
        session_factory=session_factory,
    ).download(candidate, cookies=cookies)


def download_media_candidates(
    candidates: Sequence[MediaCandidate],
    assets_dir: str | Path,
    *,
    cookies: Sequence[Mapping[str, object]],
    timeout_seconds: float,
    session_factory: Callable[[], requests.Session] = requests.Session,
) -> tuple[MediaDownloadResult, ...]:
    downloader = RequestsMediaDownloader(
        assets_dir,
        timeout_seconds=timeout_seconds,
        session_factory=session_factory,
    )
    return tuple(
        downloader.download(candidate, cookies=cookies)
        for candidate in candidates
    )


def _write_response_body(response, path: Path, *, append: bool) -> int:
    written = 0
    with path.open("ab" if append else "wb") as output:
        for chunk in response.iter_content(chunk_size=STREAM_CHUNK_SIZE):
            if not chunk:
                continue
            output.write(chunk)
            written += len(chunk)
    return written


def _parse_content_range(value: str) -> tuple[int, int, int] | None:
    match = CONTENT_RANGE_PATTERN.fullmatch(str(value or "").strip())
    if match is None or match.group("total") == "*":
        return None
    start = int(match.group("start"))
    end = int(match.group("end"))
    total = int(match.group("total"))
    if start < 0 or end < start or total <= end:
        return None
    return start, end, total


def _filtered_request_headers(headers: Mapping[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_name, raw_value in dict(headers or {}).items():
        normalized_name = str(raw_name).strip().lower()
        if normalized_name not in FORWARDED_REQUEST_HEADERS:
            continue
        result["-".join(part.capitalize() for part in normalized_name.split("-"))] = str(
            raw_value
        )
    return result


def _apply_cookies(session, cookies: Sequence[Mapping[str, object]]) -> None:
    cookie_jar = session.cookies
    for cookie in cookies:
        name = str(cookie.get("name") or "").strip()
        if not name:
            continue
        value = str(cookie.get("value") or "")
        setter = getattr(cookie_jar, "set", None)
        if callable(setter):
            options: dict[str, str] = {}
            domain = str(cookie.get("domain") or "").strip()
            path = str(cookie.get("path") or "").strip()
            if domain:
                options["domain"] = domain
            if path:
                options["path"] = path
            setter(name, value, **options)
        else:
            cookie_jar[name] = value


def _build_target_path(assets_dir: Path, url: str, content_type: str) -> Path:
    kind = "audio" if _is_audio(url, content_type) else "video"
    extension = _media_extension(url, content_type)
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return assets_dir / kind / f"{digest}{extension}"


def _media_extension(url: str, content_type: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix and len(suffix) <= 8:
        return suffix
    if content_type in MEDIA_CONTENT_TYPE_EXTENSIONS:
        return MEDIA_CONTENT_TYPE_EXTENSIONS[content_type]
    return mimetypes.guess_extension(content_type) or ".bin"


def _is_audio(url: str, content_type: str) -> bool:
    if content_type.startswith("audio/"):
        return True
    return Path(urlparse(url).path).suffix.lower() in {".mp3", ".m4a", ".wav", ".ogg"}


def _is_m3u8(url: str, content_type: str) -> bool:
    return Path(urlparse(url).path).suffix.lower() == ".m3u8" or content_type in {
        "application/vnd.apple.mpegurl",
        "application/x-mpegurl",
    }


def _is_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def _normalize_content_type(value: str) -> str:
    return str(value or "").split(";", 1)[0].strip().lower()


def _normalized_headers(headers: Mapping[str, object]) -> dict[str, str]:
    return {str(name).lower(): str(value) for name, value in dict(headers or {}).items()}


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _failure(source_url: str, content_type: str, message: str) -> MediaDownloadResult:
    return MediaDownloadResult(
        ok=False,
        source_url=source_url,
        content_type=content_type,
        message=message,
    )


__all__ = [
    "MediaCandidate",
    "MediaDownloadResult",
    "RequestsMediaDownloader",
    "download_media_candidate",
    "download_media_candidates",
]
