from __future__ import annotations

import unittest
import socket
import time
from pathlib import Path
from urllib import request
from urllib.error import URLError


class AppLayoutTest(unittest.TestCase):
    def test_root_app_compatibility_package_has_been_removed(self) -> None:
        project_root = Path(__file__).resolve().parents[1]

        self.assertFalse((project_root / "app").exists())

    def test_debug_tools_are_not_kept_under_production_src(self) -> None:
        project_root = Path(__file__).resolve().parents[1]

        self.assertFalse((project_root / "src" / "tools").exists())

    def test_webview_static_dir_lives_under_src_directory(self) -> None:
        from src.app.pywebview_app.config import WEBVIEW_DIR

        normalized = WEBVIEW_DIR.as_posix()

        self.assertTrue(normalized.endswith("/src/webview"))

    def test_pywebview_content_resize_keeps_user_selected_width(self) -> None:
        from src.app.pywebview_app.window_content_size import calculate_outer_size_for_content

        next_width, next_height = calculate_outer_size_for_content(
            outer_size=(1440, 720),
            client_size=(1424, 681),
            content_height=810,
            min_size=(1200, 675),
        )

        self.assertEqual(next_width, 1440)
        self.assertEqual(next_height, 849)

    def test_pywebview_aspect_resize_targets_client_area_ratio(self) -> None:
        from src.app.pywebview_app.window_aspect import calculate_aspect_size

        next_width, next_height = calculate_aspect_size(
            width=1200,
            height=675,
            previous_width=960,
            previous_height=540,
            ratio=16 / 9,
            min_size=(960, 540),
            frame_size=(13, 36),
        )

        self.assertEqual(next_width, 1200)
        self.assertEqual(next_height, 704)

    def test_pywebview_aspect_frame_size_uses_logical_event_size(self) -> None:
        from src.app.pywebview_app.window_aspect import calculate_logical_frame_size

        frame_width, frame_height = calculate_logical_frame_size(
            outer_size=(1200, 675),
            native_outer_size=(2400, 1350),
            native_client_size=(2374, 1278),
        )

        self.assertEqual(frame_width, 13)
        self.assertEqual(frame_height, 36)

    def test_pywebview_aspect_bind_corrects_initial_client_area_on_shown(self) -> None:
        from src.app.pywebview_app.window_aspect import bind_aspect_ratio

        class FakeEvent:
            def __init__(self) -> None:
                self.handlers = []

            def __iadd__(self, handler):
                self.handlers.append(handler)
                return self

            def fire(self) -> None:
                for handler in self.handlers:
                    handler()

        class FakeSize:
            def __init__(self, width: int, height: int) -> None:
                self.Width = width
                self.Height = height

        class FakeNative:
            _scale = 1
            Size = FakeSize(1200, 675)
            ClientSize = FakeSize(1184, 636)

        class FakeWindow:
            def __init__(self) -> None:
                self.native = FakeNative()
                self.events = type("FakeEvents", (), {
                    "resized": FakeEvent(),
                    "shown": FakeEvent(),
                })()
                self.resize_calls: list[tuple[int, int]] = []

            def resize(self, width: int, height: int) -> None:
                self.resize_calls.append((width, height))

        window = FakeWindow()
        bind_aspect_ratio(window, 16 / 9, (960, 540))
        window.events.shown.fire()

        self.assertEqual(window.resize_calls, [(1200, 705)])

    def test_vue_app_does_not_force_pywebview_size_after_user_resize(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        app_source = (project_root / "vue-project" / "src" / "App.vue").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("resizeWindowToContent", app_source)
        self.assertNotIn("scheduleContentResizeReport", app_source)

    def test_impeccable_live_script_is_not_loaded_by_default(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        checked_files = (
            project_root / "vue-project" / "index.html",
            project_root / "src" / "webview" / "index.html",
        )

        for path in checked_files:
            html = path.read_text(encoding="utf-8", errors="ignore")
            self.assertNotIn("localhost:8400/live.js", html, str(path))
            self.assertNotIn("impeccable-live-start", html, str(path))
            self.assertNotIn("impeccable-live-end", html, str(path))

    def test_fastapi_server_serves_webview_page_and_api_together(self) -> None:
        from src.app.fastapi_app import FastApiServer

        api_server = FastApiServer(host="127.0.0.1", port=_find_free_port())
        try:
            api_server.start()

            index_status, index_body = _read_url_with_retry(api_server.webview_url)
            api_status, api_body = _read_url_with_retry(f"{api_server.url}/api/status")

            self.assertEqual(index_status, 200)
            self.assertIn("Access WeChat Article", index_body)
            self.assertEqual(api_status, 200)
            self.assertIn('"status":"ready"', api_body.replace(" ", ""))
            self.assertNotIn(":8765", api_server.webview_url)
            self.assertEqual(api_server.webview_url, f"{api_server.url}/index.html")
        finally:
            api_server.stop()

    def test_legacy_webview_static_server_still_can_proxy_api_for_fallback(self) -> None:
        from src.app.pywebview_app.webview_server import WebviewStaticServer
        from src.app.fastapi_app import FastApiServer

        api_server = FastApiServer(host="127.0.0.1", port=_find_free_port())
        static_server = None
        try:
            api_server.start()
            static_server = WebviewStaticServer(port=0, api_base_url=api_server.url)
            static_server.start()

            response_status, body = _read_url_with_retry(f"{static_server.base_url}/api/status")

            self.assertEqual(response_status, 200)
            self.assertIn('"status":"ready"', body.replace(" ", ""))
        finally:
            if static_server is not None:
                static_server.stop()
            api_server.stop()


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _read_url_with_retry(url: str, attempts: int = 20) -> tuple[int, str]:
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            with request.urlopen(url, timeout=10) as response:
                return response.status, response.read().decode("utf-8")
        except URLError as exc:
            last_error = exc
            time.sleep(0.1)
    raise AssertionError(f"请求测试服务失败：{last_error}")


if __name__ == "__main__":
    unittest.main()
