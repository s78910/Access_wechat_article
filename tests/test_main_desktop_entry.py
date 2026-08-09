from __future__ import annotations

import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import main


class _FakeDesktopServer:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class _FakeWebview:
    def __init__(self, *, start_error: Exception | None = None) -> None:
        self.start_error = start_error
        self.window_call: tuple[tuple[object, ...], dict[str, object]] | None = None
        self.start_call: dict[str, object] | None = None

    def create_window(self, *args: object, **kwargs: object) -> object:
        self.window_call = (args, kwargs)
        return object()

    def start(self, **kwargs: object) -> None:
        self.start_call = kwargs
        if self.start_error is not None:
            raise self.start_error


class _FakeUvicornServer:
    def __init__(self, config: object) -> None:
        self.config = config
        self.started = False
        self.should_exit = False
        self.force_exit = False

    def run(self) -> None:
        self.started = True
        while not self.should_exit:
            time.sleep(0.001)


class MainDesktopEntryTests(unittest.TestCase):
    def test_run_desktop_app_opens_built_page_and_stops_backend(self) -> None:
        server = _FakeDesktopServer()
        webview = _FakeWebview()

        main.run_desktop_app(server=server, webview_module=webview)

        self.assertTrue(server.started)
        self.assertTrue(server.stopped)
        self.assertIsNotNone(webview.window_call)
        args, kwargs = webview.window_call or ((), {})
        self.assertEqual(args[:2], (main.APP_NAME, main.WEBVIEW_URL))
        self.assertEqual(kwargs["width"], 1200)
        self.assertEqual(kwargs["height"], 675)
        self.assertEqual(kwargs["min_size"], (960, 540))
        self.assertEqual(webview.start_call, {"icon": str(main.WINDOW_ICON_PATH)})

    def test_run_desktop_app_stops_backend_when_webview_fails(self) -> None:
        server = _FakeDesktopServer()
        webview = _FakeWebview(start_error=RuntimeError("webview failed"))

        with self.assertRaisesRegex(RuntimeError, "webview failed"):
            main.run_desktop_app(server=server, webview_module=webview)

        self.assertTrue(server.stopped)

    def test_embedded_server_reuses_current_backend_and_uvicorn_lifecycle(self) -> None:
        backend = object()
        app = object()
        config = object()
        fake_uvicorn_server = _FakeUvicornServer(config)

        with (
            patch.object(main, "ensure_dev_server_port_available") as ensure_port,
            patch.object(main, "create_dev_backend", return_value=backend) as create_backend,
            patch.object(main, "create_backend_app", return_value=app) as create_app,
            patch.object(main.uvicorn, "Config", return_value=config) as create_config,
            patch.object(main.uvicorn, "Server", return_value=fake_uvicorn_server),
        ):
            server = main.EmbeddedFastApiServer(startup_timeout_seconds=0.5)
            server.start()
            server.stop()

        ensure_port.assert_called_once_with(main.DEFAULT_API_HOST, main.DEFAULT_API_PORT)
        create_backend.assert_called_once_with()
        create_app.assert_called_once_with(backend)
        create_config.assert_called_once_with(
            app,
            host=main.DEFAULT_API_HOST,
            port=main.DEFAULT_API_PORT,
            log_level="warning",
            access_log=False,
        )
        self.assertTrue(fake_uvicorn_server.should_exit)
        self.assertFalse(server.is_running)

    def test_missing_webview_build_is_rejected_before_startup(self) -> None:
        with TemporaryDirectory() as directory:
            missing_index = Path(directory) / "index.html"
            with patch.object(main, "WEBVIEW_INDEX_PATH", missing_index):
                with self.assertRaisesRegex(FileNotFoundError, "前端构建页面不存在"):
                    main.ensure_webview_build()


if __name__ == "__main__":
    unittest.main()
