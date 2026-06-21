from __future__ import annotations

import ctypes
import platform
from dataclasses import dataclass
from typing import Any, Callable


INTERNET_SETTINGS_PATH = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"


@dataclass(frozen=True)
class ProxySnapshot:
    enabled: bool
    server: str
    readable: bool = True
    read_error: str = ""


class WindowsSystemProxy:
    """通过 Windows 注册表切换系统代理，并在变更后通知系统刷新。"""

    def __init__(
        self,
        winreg_module: Any | None = None,
        platform_name: str | None = None,
        notifier: Callable[[], None] | None = None,
    ) -> None:
        self._platform_name = platform_name or platform.system()
        self._winreg = winreg_module
        self._notifier = notifier or self._notify_windows_proxy_changed

    def enable(self, host: str, port: int) -> ProxySnapshot:
        if self._platform_name != "Windows":
            self._notifier()
            return ProxySnapshot(enabled=False, server="")

        winreg = self._get_winreg()
        access = winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS_PATH, 0, access)
        try:
            snapshot = self._read_snapshot(winreg, key)
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"{host}:{port}")
        finally:
            winreg.CloseKey(key)

        self._notifier()
        return snapshot

    def read_current(self) -> ProxySnapshot:
        """读取当前 Windows 系统代理状态，用于页面展示真实代理开关。"""
        if self._platform_name != "Windows":
            return ProxySnapshot(enabled=False, server="")

        winreg = self._get_winreg()
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS_PATH, 0, winreg.KEY_QUERY_VALUE)
        try:
            return self._read_snapshot(winreg, key)
        finally:
            winreg.CloseKey(key)

    def restore(self, snapshot: ProxySnapshot | None) -> None:
        if not snapshot or self._platform_name != "Windows":
            self._notifier()
            return

        winreg = self._get_winreg()
        access = winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS_PATH, 0, access)
        try:
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1 if snapshot.enabled else 0)
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, snapshot.server)
        finally:
            winreg.CloseKey(key)

        self._notifier()

    def _get_winreg(self):
        if self._winreg:
            return self._winreg

        import winreg

        self._winreg = winreg
        return winreg

    def _read_snapshot(self, winreg, key) -> ProxySnapshot:
        try:
            enabled = bool(winreg.QueryValueEx(key, "ProxyEnable")[0])
        except FileNotFoundError:
            enabled = False

        try:
            server = str(winreg.QueryValueEx(key, "ProxyServer")[0])
        except FileNotFoundError:
            server = ""

        return ProxySnapshot(enabled=enabled, server=server)

    def _notify_windows_proxy_changed(self) -> None:
        if self._platform_name != "Windows":
            return

        try:
            internet_set_option = ctypes.windll.Wininet.InternetSetOptionW
            internet_set_option(0, 39, 0, 0)
            internet_set_option(0, 37, 0, 0)
        except Exception:
            # 注册表已经写入成功，刷新失败只影响立即生效速度，不能阻断恢复流程。
            return
