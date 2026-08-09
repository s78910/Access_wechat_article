from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from src.domain.enums import ProcessMessageType
from src.modules.processes.mitm_capture_session import MitmCaptureSession
from src.modules.processes.process_channel import ProcessChannel
from src.modules.proxy.capture_buffer import CaptureBuffer
from src.modules.proxy.mitmproxy_listener import MitmproxyListener
from src.modules.proxy.proxy_lifecycle import ProxyLifecycle
from src.modules.proxy.proxy_state import ProxySnapshot
from src.modules.system.windows_system_proxy import WindowsSystemProxy


def run_mitm_capture_process(
    *,
    connection: Any,
    task_id: str,
    attempt_id: str,
    expected_proxy_lease_id: str,
) -> None:
    """Windows spawn 子进程入口；只执行一个 attempt 后退出。"""
    channel = ProcessChannel(
        connection,
        task_id=task_id,
        attempt_id=attempt_id,
    )
    buffer = CaptureBuffer(task_id=task_id, attempt_id=attempt_id)

    def publish_snapshot(snapshot: ProxySnapshot) -> None:
        channel.send(
            ProcessMessageType.PROXY_SNAPSHOT,
            {"snapshot": snapshot.to_dict()},
        )

    def lifecycle_factory(proxy_lease_id: str, payload: dict[str, Any]) -> ProxyLifecycle:
        return build_proxy_lifecycle(
            proxy_lease_id=proxy_lease_id,
            payload=payload,
            buffer=buffer,
            publish_snapshot=publish_snapshot,
        )

    MitmCaptureSession(
        channel=channel,
        buffer=buffer,
        expected_proxy_lease_id=expected_proxy_lease_id,
        lifecycle_factory=lifecycle_factory,
        # START_CAPTURE 可以覆盖此兜底值；它只用于防止父进程永久失联。
        capture_timeout_seconds=60.0,
    ).run(start_timeout_seconds=30.0)


def build_proxy_lifecycle(
    *,
    proxy_lease_id: str,
    payload: Mapping[str, Any],
    buffer: CaptureBuffer,
    publish_snapshot: Callable[[ProxySnapshot], None],
    listener_factory: Callable[..., Any] = MitmproxyListener,
    system_proxy_factory: Callable[[], Any] = WindowsSystemProxy,
) -> ProxyLifecycle:
    """仅使用 START_CAPTURE 参数组装代理会话，不在子进程读取配置文件。"""
    host = str(payload.get("host", "127.0.0.1")).strip()
    port = int(payload.get("port", 18000))
    confdir_value = str(payload.get("confdir", "")).strip()
    ready_timeout_seconds = float(payload.get("ready_timeout_seconds", 5.0))
    shutdown_timeout_seconds = float(payload.get("shutdown_timeout_seconds", 3.0))
    if not host:
        raise ValueError("MITM host 不能为空")
    if not 1 <= port <= 65535:
        raise ValueError("MITM port 必须在 1 到 65535 之间")
    if not confdir_value:
        raise ValueError("MITM confdir 不能为空")
    if ready_timeout_seconds <= 0 or shutdown_timeout_seconds <= 0:
        raise ValueError("MITM READY 和关闭超时必须大于 0")

    listener = listener_factory(
        host=host,
        port=port,
        confdir=Path(confdir_value),
        ssl_insecure=bool(payload.get("ssl_insecure", True)),
        buffer=buffer,
        ready_timeout_seconds=ready_timeout_seconds,
        shutdown_timeout_seconds=shutdown_timeout_seconds,
    )
    return ProxyLifecycle(
        listener=listener,
        system_proxy=system_proxy_factory(),
        proxy_address=f"{host}:{port}",
        proxy_lease_id=proxy_lease_id,
        publish_snapshot=publish_snapshot,
    )
