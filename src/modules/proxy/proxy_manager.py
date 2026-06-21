from __future__ import annotations

from src.core.config import ProxyConfig
from src.modules.proxy.system_proxy import ProxySnapshot, WindowsSystemProxy


class ProxyManager:
    """负责本机系统代理开关，保存原始状态用于停止任务时恢复。"""

    def __init__(
        self,
        config: ProxyConfig | None = None,
        system_proxy: WindowsSystemProxy | None = None,
    ) -> None:
        self.config = config or ProxyConfig()
        self.system_proxy = system_proxy or WindowsSystemProxy()
        self._snapshot: ProxySnapshot | None = None

    @property
    def is_enabled(self) -> bool:
        return self._snapshot is not None

    def start(self) -> ProxySnapshot | None:
        if self._snapshot is not None:
            return self._snapshot

        # enable_system_proxy 只决定启动任务时是否自动接管；用户手动点击系统代理开关时仍应生效。
        self._snapshot = self.system_proxy.enable(self.config.host, self.config.port)
        return self._snapshot

    def stop(self) -> None:
        if self._snapshot is None:
            return

        snapshot = self._snapshot
        self._snapshot = None
        self.system_proxy.restore(snapshot)

    def current_snapshot(self) -> ProxySnapshot:
        """返回当前系统代理状态，不依赖本程序是否曾经开启过代理。"""
        return self.system_proxy.read_current()
