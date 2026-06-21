from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib import request
from urllib.error import HTTPError, URLError

from .config import DEFAULT_HOST, DEFAULT_PORT, WEBVIEW_DIR


class QuietStaticHandler(SimpleHTTPRequestHandler):
    """静态文件处理器，同时把 pywebview 内的 /api 请求代理到 FastAPI。"""

    api_base_url = ""

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        if self._proxy_api_request():
            return
        super().do_GET()

    def do_POST(self) -> None:
        if self._proxy_api_request():
            return
        super().do_POST()

    def do_OPTIONS(self) -> None:
        if self._proxy_api_request():
            return
        super().do_OPTIONS()

    def _proxy_api_request(self) -> bool:
        if not self.path.startswith("/api"):
            return False
        if not self.api_base_url:
            self.send_error(HTTPStatus.BAD_GATEWAY, "API server is not configured")
            return True

        body_length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(body_length) if body_length > 0 else None
        target_url = f"{self.api_base_url}{self.path}"
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"host", "content-length", "connection"}
        }
        api_request = request.Request(target_url, data=body, headers=headers, method=self.command)
        try:
            with request.urlopen(api_request, timeout=10) as response:
                response_body = response.read()
                self.send_response(response.status)
                self._copy_response_headers(response.headers, len(response_body))
                self.end_headers()
                self.wfile.write(response_body)
        except HTTPError as exc:
            response_body = exc.read()
            self.send_response(exc.code)
            self._copy_response_headers(exc.headers, len(response_body))
            self.end_headers()
            self.wfile.write(response_body)
        except URLError as exc:
            message = f"API server unavailable: {exc}".encode("utf-8", errors="ignore")
            self.send_response(HTTPStatus.BAD_GATEWAY)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(message)))
            self.end_headers()
            self.wfile.write(message)
        return True

    def _copy_response_headers(self, headers, content_length: int) -> None:
        skipped = {"connection", "transfer-encoding", "content-length", "date", "server"}
        for key, value in headers.items():
            if key.lower() not in skipped:
                self.send_header(key, value)
        self.send_header("Content-Length", str(content_length))


class WebviewStaticServer:
    """给 Vue 构建产物提供本地 HTTP 访问，避免 file:// 下模块脚本加载失败。"""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, api_base_url: str = "") -> None:
        self.host = host
        self.port = port
        self.api_base_url = api_base_url.rstrip("/")
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None

    @property
    def base_url(self) -> str:
        if not self._server:
            return f"http://{self.host}:{self.port}"

        host, port = self._server.server_address
        return f"http://{host}:{port}"

    @property
    def index_url(self) -> str:
        return f"{self.base_url}/index.html"

    def start(self) -> None:
        if self._server:
            return

        if not (WEBVIEW_DIR / "index.html").exists():
            raise FileNotFoundError(f"未找到前端入口文件：{WEBVIEW_DIR / 'index.html'}")

        handler_class = type(
            "WebviewStaticHandler",
            (QuietStaticHandler,),
            {"api_base_url": self.api_base_url},
        )
        handler = partial(handler_class, directory=str(WEBVIEW_DIR))
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._server:
            return

        self._server.shutdown()
        self._server.server_close()

        if self._thread:
            self._thread.join(timeout=3)

        self._server = None
        self._thread = None
