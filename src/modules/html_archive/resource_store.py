from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class SavedAsset:
    url: str
    local_path: Path
    relative_path: str
    kind: str
    content_type: str


EXT_KIND = {
    ".jpg": "img",
    ".jpeg": "img",
    ".png": "img",
    ".gif": "img",
    ".webp": "img",
    ".svg": "img",
    ".ico": "img",
    ".css": "css",
    ".js": "js",
    ".mjs": "js",
    ".woff": "font",
    ".woff2": "font",
    ".ttf": "font",
    ".otf": "font",
    ".eot": "font",
}

CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/x-icon": ".ico",
    "text/css": ".css",
    "application/javascript": ".js",
    "text/javascript": ".js",
    "application/x-javascript": ".js",
    "font/woff": ".woff",
    "font/woff2": ".woff2",
    "application/font-woff": ".woff",
    "application/font-woff2": ".woff2",
    "application/octet-stream": "",
}


def save_asset(assets_dir: Path, *, url: str, data: bytes, content_type: str = "") -> SavedAsset:
    kind = infer_asset_kind(url, content_type)
    ext = infer_asset_extension(url, content_type)
    filename = f"{hashlib.sha256(str(url).encode('utf-8')).hexdigest()[:16]}{ext}"
    local_dir = Path(assets_dir) / kind
    local_dir.mkdir(parents=True, exist_ok=True)
    local_path = local_dir / filename
    if not local_path.exists():
        local_path.write_bytes(data)
    relative_path = f"{Path(assets_dir).name}/{kind}/{filename}"
    return SavedAsset(url=url, local_path=local_path, relative_path=relative_path, kind=kind, content_type=content_type)


def infer_asset_kind(url: str, content_type: str = "") -> str:
    lower_type = content_type.lower().split(";")[0].strip()
    if lower_type.startswith("image/"):
        return "img"
    if lower_type.startswith("font/"):
        return "font"
    if lower_type == "text/css":
        return "css"
    if "javascript" in lower_type or lower_type == "text/ecmascript":
        return "js"
    ext = Path(urlparse(str(url)).path).suffix.lower()
    return EXT_KIND.get(ext, "other")


def infer_asset_extension(url: str, content_type: str = "") -> str:
    ext = Path(urlparse(str(url)).path).suffix.lower()
    if ext and len(ext) <= 8:
        return ext
    lower_type = content_type.lower().split(";")[0].strip()
    mapped = CONTENT_TYPE_EXT.get(lower_type)
    if mapped is not None:
        return mapped
    guessed = mimetypes.guess_extension(lower_type)
    return guessed or ""


__all__ = ["SavedAsset", "infer_asset_extension", "infer_asset_kind", "save_asset"]
