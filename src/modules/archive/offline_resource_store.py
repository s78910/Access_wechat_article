from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "text/css": ".css",
    "font/woff": ".woff",
    "font/woff2": ".woff2",
    "application/font-woff": ".woff",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
}


@dataclass(frozen=True, slots=True)
class SavedOfflineResource:
    url: str
    local_path: Path
    relative_path: str
    content_type: str


def save_offline_resource(
    assets_dir: str | Path,
    *,
    url: str,
    body: bytes,
    content_type: str,
) -> SavedOfflineResource:
    root = Path(assets_dir)
    kind = _resource_kind(content_type, url)
    extension = _resource_extension(content_type, url)
    filename = f"{hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]}{extension}"
    target = root / kind / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    return SavedOfflineResource(
        url=url,
        local_path=target,
        relative_path=f"{root.name}/{kind}/{filename}",
        content_type=content_type,
    )


def _resource_kind(content_type: str, url: str) -> str:
    normalized = content_type.split(";", 1)[0].strip().lower()
    if normalized.startswith("image/"):
        return "img"
    if normalized.startswith("video/"):
        return "video"
    if normalized.startswith("audio/"):
        return "audio"
    if normalized.startswith("font/") or "font" in normalized:
        return "font"
    if normalized == "text/css":
        return "css"
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in {".mp4", ".webm", ".m3u8", ".ts"}:
        return "video"
    if suffix in {".mp3", ".m4a", ".wav", ".ogg"}:
        return "audio"
    return "other"


def _resource_extension(content_type: str, url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix and len(suffix) <= 8:
        return suffix
    normalized = content_type.split(";", 1)[0].strip().lower()
    if normalized in CONTENT_TYPE_EXTENSIONS:
        return CONTENT_TYPE_EXTENSIONS[normalized]
    return mimetypes.guess_extension(normalized) or ""


__all__ = ["SavedOfflineResource", "save_offline_resource"]
