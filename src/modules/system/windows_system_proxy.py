from __future__ import annotations

import ctypes
import platform
from typing import Any, Callable

from src.modules.proxy.proxy_state import ProxySnapshot


INTERNET_SETTINGS_PATH = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"


class WindowsSystemProxy:
    """读写当前 Windows 用户的系统代理，并在变更后通知 WinINet。"""

    def __init__(
        self,
        *,
        winreg_module: Any | None = None,
        platform_name: str | None = None,
        notifier: Callable[[], None] | None = None,
    ) -> None:
        self._winreg = winreg_module
        self._platform_name = platform_name or platform.system()
        self._notifier = notifier or self._notify_windows_proxy_changed

    def snapshot(self) -> ProxySnapshot:
        self._require_windows()
        winreg = self._get_winreg()
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            INTERNET_SETTINGS_PATH,
            0,
            winreg.KEY_QUERY_VALUE,
        )
        try:
            return ProxySnapshot(
                enabled=bool(self._read_value(winreg, key, "ProxyEnable", 0)),
                server=str(self._read_value(winreg, key, "ProxyServer", "")),
                bypass=str(self._read_value(winreg, key, "ProxyOverride", "")),
                auto_config_url=str(self._read_value(winreg, key, "AutoConfigURL", "")),
            )
        finally:
            winreg.CloseKey(key)

    def current(self) -> ProxySnapshot:
        return self.snapshot()

    def enable(self, server: str) -> None:
        self._require_windows()
        if not server.strip():
            raise ValueError("系统代理地址不能为空")
        winreg = self._get_winreg()
        access = winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS_PATH, 0, access)
        try:
            # 先写目标地址，再开启开关，避免短暂指向原有代理地址。
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, server)
            winreg.SetValueEx(key, "AutoConfigURL", 0, winreg.REG_SZ, "")
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
        finally:
            winreg.CloseKey(key)
        self._notifier()

    def restore(self, snapshot: ProxySnapshot) -> None:
        self._require_windows()
        winreg = self._get_winreg()
        access = winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS_PATH, 0, access)
        try:
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, snapshot.server)
            # 捕获期间不修改 ProxyOverride，恢复时也不覆盖用户可能做出的新调整。
            winreg.SetValueEx(key, "AutoConfigURL", 0, winreg.REG_SZ, snapshot.auto_config_url)
            winreg.SetValueEx(
                key,
                "ProxyEnable",
                0,
                winreg.REG_DWORD,
                1 if snapshot.enabled else 0,
            )
        finally:
            winreg.CloseKey(key)
        self._notifier()

    def _get_winreg(self) -> Any:
        if self._winreg is None:
            import winreg

            self._winreg = winreg
        return self._winreg

    def _require_windows(self) -> None:
        if self._platform_name != "Windows":
            raise OSError("系统代理控制仅支持 Windows")

    @staticmethod
    def _read_value(winreg: Any, key: Any, name: str, default: Any) -> Any:
        try:
            return winreg.QueryValueEx(key, name)[0]
        except FileNotFoundError:
            return default

    @staticmethod
    def _notify_windows_proxy_changed() -> None:
        try:
            internet_set_option = ctypes.windll.Wininet.InternetSetOptionW
            internet_set_option(0, 39, 0, 0)
            internet_set_option(0, 37, 0, 0)
        except Exception:
            # 注册表值已经写入；通知失败只影响系统读取新值的速度。
            return
