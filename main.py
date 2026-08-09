from __future__ import annotations

import importlib
import os
import threading
import time
from pathlib import Path
from typing import Any

import uvicorn

from dev_server import (
    DEFAULT_API_HOST,
    DEFAULT_API_PORT,
    create_backend_app,
    create_dev_backend,
    ensure_dev_server_port_available,
    shutdown_backend,
)


APP_NAME = "Access WeChat Article"
PROJECT_ROOT = Path(__file__).resolve().parent
WEBVIEW_DIR = PROJECT_ROOT / "src" / "webview"
WEBVIEW_INDEX_PATH = WEBVIEW_DIR / "index.html"
WINDOW_ICON_PATH = WEBVIEW_DIR / "favicon.ico"
WEBVIEW_URL = f"http://{DEFAULT_API_HOST}:{DEFAULT_API_PORT}/index.html"

WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 675
WINDOW_MIN_SIZE = (960, 540)
SERVER_STARTUP_TIMEOUT_SECONDS = 10.0
SERVER_SHUTDOWN_TIMEOUT_SECONDS = 5.0


def ensure_webview_build() -> Path:
    """确认 Vue 构建产物存在，避免桌面窗口启动后只显示空白页。"""
    if not WEBVIEW_INDEX_PATH.is_file():
        raise FileNotFoundError(
            f"前端构建页面不存在：{WEBVIEW_INDEX_PATH}。请先构建 Vue 页面。"
        )
    return WEBVIEW_INDEX_PATH


class EmbeddedFastApiServer:
    """在桌面进程的后台线程中运行现有 FastAPI 应用。"""

    def __init__(
        self,
        *,
        host: str = DEFAULT_API_HOST,
        port: int = DEFAULT_API_PORT,
        startup_timeout_seconds: float = SERVER_STARTUP_TIMEOUT_SECONDS,
        shutdown_timeout_seconds: float = SERVER_SHUTDOWN_TIMEOUT_SECONDS,
    ) -> None:
        self.host = str(host)
        self.port = int(port)
        self.startup_timeout_seconds = max(0.1, float(startup_timeout_seconds))
        self.shutdown_timeout_seconds = max(0.1, float(shutdown_timeout_seconds))
        self._backend: Any | None = None
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return bool(self._thread is not None and self._thread.is_alive())

    def start(self) -> None:
        if self.is_running:
            return

        ensure_webview_build()
        ensure_dev_server_port_available(self.host, self.port)
        backend = create_dev_backend()
        self._backend = backend

        try:
            app = create_backend_app(backend)
            config = uvicorn.Config(
                app,
                host=self.host,
                port=self.port,
                log_level="warning",
                access_log=False,
            )
            server = uvicorn.Server(config)
            thread = threading.Thread(
                target=server.run,
                name="awa-fastapi",
                daemon=True,
            )
            self._server = server
            self._thread = thread
            thread.start()
            self._wait_until_started()
        except Exception:
            server_started = bool(self._server is not None and self._server.started)
            failed_backend = self._backend
            self.stop()
            # Uvicorn 未进入 lifespan 时，需要由桌面入口主动释放后端上下文。
            if failed_backend is not None and not server_started:
                shutdown_backend(failed_backend)
            raise

    def stop(self) -> None:
        server = self._server
        thread = self._thread

        if server is not None:
            server.should_exit = True
        if thread is not None and thread.is_alive():
            thread.join(timeout=self.shutdown_timeout_seconds)
        if thread is not None and thread.is_alive() and server is not None:
            server.force_exit = True
            thread.join(timeout=1.0)

        self._server = None
        self._thread = None
        self._backend = None

    def _wait_until_started(self) -> None:
        server = self._server
        thread = self._thread
        if server is None or thread is None:
            raise RuntimeError("FastAPI 后端尚未创建")

        deadline = time.monotonic() + self.startup_timeout_seconds
        while time.monotonic() < deadline:
            if server.started:
                return
            if not thread.is_alive():
                raise RuntimeError("FastAPI 后端启动失败，服务线程已提前退出")
            time.sleep(0.05)
        raise TimeoutError(
            f"FastAPI 后端在 {self.startup_timeout_seconds:g} 秒内未完成启动"
        )


def run_desktop_app(
    *,
    server: EmbeddedFastApiServer | Any | None = None,
    webview_module: Any | None = None,
) -> None:
    """启动本地 API，再使用 PyWebView 打开已经构建好的前端页面。"""
    ensure_webview_build()
    desktop_server = server or EmbeddedFastApiServer()
    webview = webview_module or importlib.import_module("webview")

    desktop_server.start()
    try:
        webview.create_window(
            APP_NAME,
            WEBVIEW_URL,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            min_size=WINDOW_MIN_SIZE,
        )
        webview.start(icon=str(WINDOW_ICON_PATH))
    finally:
        desktop_server.stop()


def _show_startup_error(message: str) -> None:
    text = f"程序启动失败：{message}"
    print(text)
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 0x10)
    except Exception:
        # 图形提示不可用时保留终端错误，不覆盖原始异常。
        return


def main() -> None:
    try:
        run_desktop_app()
    except KeyboardInterrupt:
        return
    except Exception as exc:
        _show_startup_error(str(exc))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
