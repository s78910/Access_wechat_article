from __future__ import annotations

import socket
import unittest
from unittest.mock import patch

import dev_server
from src.core.config import AppFeatureConfig, AppRuntimeConfig, ProxyConfig


class FakeFastApiServer:
    instances: list["FakeFastApiServer"] = []

    def __init__(self, api=None, host: str = "", port: int = 0) -> None:
        self.api = api
        self.host = host
        self.port = port
        self.url = f"http://{host}:{port}"
        self.started = False
        self.stopped = False
        FakeFastApiServer.instances.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class FakeWebviewApi:
    instances: list["FakeWebviewApi"] = []

    def __init__(self, runtime_config=None, auto_start: bool = False, auto_cleanup: bool = False) -> None:
        self.runtime_config = runtime_config
        self.auto_start = auto_start
        self.auto_cleanup = auto_cleanup
        self.shutdown_called = False
        FakeWebviewApi.instances.append(self)

    def shutdown(self) -> None:
        self.shutdown_called = True


class DevServerLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        FakeFastApiServer.instances.clear()
        FakeWebviewApi.instances.clear()

    def test_create_dev_server_uses_runtime_config_and_webview_api(self) -> None:
        runtime_config = AppRuntimeConfig(
            app=AppFeatureConfig(auto_start_proxy=True),
            proxy=ProxyConfig(enable_system_proxy=True),
        )

        server, api = dev_server.create_dev_server(
            load_config=lambda: runtime_config,
            api_factory=FakeWebviewApi,
            server_factory=FakeFastApiServer,
        )

        self.assertIs(api.runtime_config, runtime_config)
        self.assertTrue(api.auto_start)
        self.assertTrue(api.auto_cleanup)
        self.assertIs(server.api, api)
        self.assertEqual(server.host, dev_server.DEFAULT_API_HOST)
        self.assertEqual(server.port, dev_server.DEFAULT_API_PORT)

    def test_shutdown_dev_server_stops_server_before_restoring_api_state(self) -> None:
        events: list[str] = []

        class OrderedServer(FakeFastApiServer):
            def stop(self) -> None:
                events.append("server.stop")
                super().stop()

        class OrderedApi(FakeWebviewApi):
            def shutdown(self) -> None:
                events.append("api.shutdown")
                super().shutdown()

        runtime_config = AppRuntimeConfig(app=AppFeatureConfig(auto_start_proxy=False))
        server, api = dev_server.create_dev_server(
            load_config=lambda: runtime_config,
            api_factory=OrderedApi,
            server_factory=OrderedServer,
        )

        dev_server.shutdown_dev_server(server, api)

        self.assertTrue(server.stopped)
        self.assertTrue(api.shutdown_called)
        self.assertEqual(events, ["server.stop", "api.shutdown"])

    def test_main_refuses_to_start_when_api_port_is_already_bound(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((dev_server.DEFAULT_API_HOST, 0))
        occupied_port = int(sock.getsockname()[1])
        sock.listen(1)
        try:
            with patch.object(dev_server, "create_dev_server") as create_server:
                with self.assertRaises(RuntimeError) as context:
                    dev_server.ensure_dev_server_port_available(dev_server.DEFAULT_API_HOST, occupied_port)
        finally:
            sock.close()

        create_server.assert_not_called()
        self.assertIn(str(occupied_port), str(context.exception))


if __name__ == "__main__":
    unittest.main()
