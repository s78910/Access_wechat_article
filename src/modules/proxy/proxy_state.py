from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ProxySnapshot:
    """程序接管前的系统代理状态，可跨进程序列化。"""

    enabled: bool
    server: str = ""
    bypass: str = ""
    auto_config_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "server": self.server,
            "bypass": self.bypass,
            "auto_config_url": self.auto_config_url,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProxySnapshot:
        return cls(
            enabled=bool(data.get("enabled", False)),
            server=str(data.get("server", "")),
            bypass=str(data.get("bypass", "")),
            auto_config_url=str(data.get("auto_config_url", "")),
        )


@dataclass(frozen=True, slots=True)
class ProxySessionState:
    proxy_lease_id: str
    proxy_address: str
    snapshot: ProxySnapshot
    listen_started_at: float


def proxy_points_to(snapshot: ProxySnapshot, proxy_address: str) -> bool:
    """仅当当前已启用代理且全部代理端点都指向本次地址时返回真。"""
    if not snapshot.enabled:
        return False
    # 捕获期间程序会清空 PAC。这里出现新 PAC 说明代理状态已被用户或其他程序接管。
    if snapshot.auto_config_url.strip():
        return False
    expected = _normalize_endpoint(proxy_address)
    raw = snapshot.server.strip()
    if not expected or not raw:
        return False

    entries = [item.strip() for item in raw.split(";") if item.strip()]
    endpoints = [item.split("=", 1)[-1] for item in entries]
    return bool(endpoints) and all(_normalize_endpoint(item) == expected for item in endpoints)


def _normalize_endpoint(value: str) -> str:
    endpoint = str(value or "").strip().lower()
    for prefix in ("http://", "https://"):
        if endpoint.startswith(prefix):
            endpoint = endpoint[len(prefix) :]
            break
    return endpoint.rstrip("/")
