from __future__ import annotations

import threading

import uvicorn

from src.app.pywebview_app.webview_api import WebviewApi
from src.app.fastapi_app.app import create_app


DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 8766


class FastApiServer:
    """可嵌入的 FastAPI/uvicorn 服务，供开发模式和 pywebview 桌面壳共用。"""

    def __init__(
        self,
        api: WebviewApi | None = None,
        host: str = DEFAULT_API_HOST,
        port: int = DEFAULT_API_PORT,
    ) -> None:
        self.api = api
        self.host = host
        self.port = int(port)
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def webview_url(self) -> str:
        return f"{self.url}/index.html"

    def start(self) -> None:
        if self._server is not None:
            return

        config = uvicorn.Config(
            create_app(self.api),
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, name="awa-fastapi", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None
