from __future__ import annotations

from pathlib import Path
import unittest

from src.domain.enums import CaptureType, TaskStatus
from src.modules.proxy.proxy_state import ProxySnapshot
from src.services.capture.in_process_mitm_capture_service import (
    InProcessMitmCaptureService,
)


class InProcessMitmCaptureServiceTests(unittest.TestCase):
    def test_start_and_stop_follow_proxy_lifecycle_order_and_freeze_html(self) -> None:
        events: list[str] = []
        system_proxy = _FakeSystemProxy(events)

        def listener_factory(**kwargs):
            return _FakeListener(events, kwargs["buffer"])

        service = InProcessMitmCaptureService(
            listener_factory=listener_factory,
            system_proxy_factory=lambda: system_proxy,
        )

        attempt = service.start_attempt(
            task_id="task001",
            attempt_id="attempt001",
            proxy_lease_id="lease001",
            proxy_address="127.0.0.1:18000",
            capture_config={
                "host": "127.0.0.1",
                "port": 18000,
                "confdir": ".mitmproxy",
                "ssl_insecure": True,
                "ready_timeout_seconds": 10,
                "shutdown_timeout_seconds": 3,
            },
        )

        ready = attempt.wait_ready(timeout_seconds=1)
        result = attempt.stop_capture(timeout_seconds=1)

        self.assertEqual(ready["proxy_address"], "127.0.0.1:18000")
        self.assertEqual(result.status, TaskStatus.SUCCESS)
        self.assertEqual(result.capture_type, CaptureType.HTML)
        self.assertEqual(result.html, "<html>ok</html>")
        self.assertEqual(
            events,
            [
                "proxy.snapshot",
                "listener.start",
                "proxy.enable:127.0.0.1:18000",
                "proxy.current",
                "proxy.current",
                "proxy.restore",
                "listener.stop",
            ],
        )

    def test_cancel_restores_proxy_and_stops_listener(self) -> None:
        events: list[str] = []
        system_proxy = _FakeSystemProxy(events)
        service = InProcessMitmCaptureService(
            listener_factory=lambda **kwargs: _FakeListener(events, kwargs["buffer"]),
            system_proxy_factory=lambda: system_proxy,
        )
        attempt = service.start_attempt(
            task_id="task001",
            attempt_id="attempt001",
            proxy_lease_id="lease001",
            proxy_address="127.0.0.1:18000",
            capture_config={
                "host": "127.0.0.1",
                "port": 18000,
                "confdir": ".mitmproxy",
                "ssl_insecure": True,
                "ready_timeout_seconds": 10,
                "shutdown_timeout_seconds": 3,
            },
        )

        attempt.cancel()

        self.assertIn("proxy.restore", events)
        self.assertEqual(events[-1], "listener.stop")


class _FakeListener:
    def __init__(self, events: list[str], buffer) -> None:
        self._events = events
        self._buffer = buffer

    def start(self) -> float:
        self._events.append("listener.start")
        self._buffer.record_html("<html>ok</html>", request_summary={"url": "https://mp.weixin.qq.com/s/test"})
        return 123.456

    def stop(self) -> None:
        self._events.append("listener.stop")


class _FakeSystemProxy:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self._snapshot = ProxySnapshot(enabled=False)
        self._current = ProxySnapshot(enabled=False)

    def snapshot(self) -> ProxySnapshot:
        self._events.append("proxy.snapshot")
        return self._snapshot

    def enable(self, server: str) -> None:
        self._events.append(f"proxy.enable:{server}")
        self._current = ProxySnapshot(enabled=True, server=server)

    def current(self) -> ProxySnapshot:
        self._events.append("proxy.current")
        return self._current

    def restore(self, snapshot: ProxySnapshot) -> None:
        self._events.append("proxy.restore")
        self._current = snapshot


if __name__ == "__main__":
    unittest.main()
