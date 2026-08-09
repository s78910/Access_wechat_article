from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from src.modules.proxy.proxy_state import ProxySessionState, ProxySnapshot, proxy_points_to


class MitmListener(Protocol):
    def start(self) -> float: ...

    def stop(self) -> None: ...


class SystemProxyController(Protocol):
    def snapshot(self) -> ProxySnapshot: ...

    def enable(self, server: str) -> None: ...

    def current(self) -> ProxySnapshot: ...

    def restore(self, snapshot: ProxySnapshot) -> None: ...


class ProxyLifecycleError(RuntimeError):
    """MITM 或系统代理开启、关闭失败。"""


class ProxyLifecycle:
    """一次性 MITM 会话的代理生命周期。

    开启顺序固定为 MITM 监听后系统代理，关闭顺序固定为系统代理后 MITM。
    常规采集不执行 HTTPS 连通性探测。
    """

    def __init__(
        self,
        *,
        listener: MitmListener,
        system_proxy: SystemProxyController,
        proxy_address: str,
        proxy_lease_id: str,
        publish_snapshot: Callable[[ProxySnapshot], None],
    ) -> None:
        if not proxy_address.strip():
            raise ValueError("proxy_address 不能为空")
        if not proxy_lease_id.strip():
            raise ValueError("proxy_lease_id 不能为空")
        self._listener = listener
        self._system_proxy = system_proxy
        self._proxy_address = proxy_address
        self._proxy_lease_id = proxy_lease_id
        self._publish_snapshot = publish_snapshot
        self._snapshot: ProxySnapshot | None = None
        self._listener_start_attempted = False
        self._proxy_enable_attempted = False
        self._active = False
        self._started_once = False

    def start(self) -> ProxySessionState:
        if self._started_once:
            raise ProxyLifecycleError("同一个代理生命周期对象不能重复启动")
        self._started_once = True

        try:
            self._snapshot = self._system_proxy.snapshot()
            # 快照必须在任何系统代理修改之前交给父进程保存。
            self._publish_snapshot(self._snapshot)

            self._listener_start_attempted = True
            listen_started_at = float(self._listener.start())

            self._proxy_enable_attempted = True
            self._system_proxy.enable(self._proxy_address)
            current = self._system_proxy.current()
            if not proxy_points_to(current, self._proxy_address):
                raise ProxyLifecycleError("系统代理未指向本次 MITM 地址")

            self._active = True
            return ProxySessionState(
                proxy_lease_id=self._proxy_lease_id,
                proxy_address=self._proxy_address,
                snapshot=self._snapshot,
                listen_started_at=listen_started_at,
            )
        except Exception as exc:
            cleanup_errors = self._cleanup()
            message = f"代理会话启动失败：{exc}"
            if cleanup_errors:
                message += f"；清理失败：{'；'.join(cleanup_errors)}"
            raise ProxyLifecycleError(message) from exc

    def stop(self) -> None:
        if not (self._active or self._listener_start_attempted or self._proxy_enable_attempted):
            return
        cleanup_errors = self._cleanup()
        if cleanup_errors:
            raise ProxyLifecycleError(f"代理会话关闭失败：{'；'.join(cleanup_errors)}")

    def _cleanup(self) -> list[str]:
        errors: list[str] = []

        # 只有当前系统代理仍明确指向本次 MITM 时，才恢复原快照，避免覆盖用户新设置。
        if self._proxy_enable_attempted and self._snapshot is not None:
            try:
                current = self._system_proxy.current()
                if proxy_points_to(current, self._proxy_address):
                    self._system_proxy.restore(self._snapshot)
            except Exception as exc:
                errors.append(f"系统代理恢复失败：{exc}")

        # 即使系统代理恢复失败，也必须继续尝试停止 MITM。
        if self._listener_start_attempted:
            try:
                self._listener.stop()
            except Exception as exc:
                errors.append(f"MITM 停止失败：{exc}")

        self._active = False
        self._proxy_enable_attempted = False
        self._listener_start_attempted = False
        return errors
