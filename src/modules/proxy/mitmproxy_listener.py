from __future__ import annotations

import asyncio
from pathlib import Path
import socket
from threading import Thread
import time
from typing import Any, Mapping

from src.modules.proxy.capture_buffer import CaptureBuffer
from src.modules.proxy.wechat_request_matcher import WechatRequestMatcher


class MitmproxyListenerError(RuntimeError):
    """mitmproxy 监听器启动或停止失败。"""


class WechatArticleCaptureAddon:
    """mitmproxy addon：只把文章主请求和 HTML 写入内存缓冲区。"""

    def __init__(self, *, buffer: CaptureBuffer, matcher: WechatRequestMatcher) -> None:
        self._buffer = buffer
        self._matcher = matcher

    def request(self, flow: Any) -> None:
        request = getattr(flow, "request", None)
        if request is None:
            return
        url = str(getattr(request, "pretty_url", "") or getattr(request, "url", "") or "")
        headers = _headers_mapping(getattr(request, "headers", None))
        match = self._matcher.match_reference(
            url,
            method=str(getattr(request, "method", "GET") or "GET"),
            headers=headers,
        )
        if match is None:
            return

        self._buffer.record_reference(
            match.to_reference(),
            request_summary=match.to_request_summary(),
        )
        if match.url_source == "request":
            # 请求已经进入 MITM 后再禁用缓存，尽量让本次点击得到真实 response。
            _set_header(getattr(request, "headers", None), "Cache-Control", "no-cache")
            _set_header(getattr(request, "headers", None), "Pragma", "no-cache")

    def response(self, flow: Any) -> None:
        request = getattr(flow, "request", None)
        response = getattr(flow, "response", None)
        if request is None or response is None:
            return
        url = str(getattr(request, "pretty_url", "") or getattr(request, "url", "") or "")
        try:
            html_text = str(response.get_text(strict=False) or "")
        except Exception:
            return
        match = self._matcher.match_html_response(
            url,
            html_text=html_text,
            status_code=int(getattr(response, "status_code", 0) or 0),
            response_headers=_headers_mapping(getattr(response, "headers", None)),
            request_headers=_headers_mapping(getattr(request, "headers", None)),
            method=str(getattr(request, "method", "GET") or "GET"),
        )
        if match is None:
            return
        self._buffer.record_reference(
            match.reference.to_reference(),
            request_summary=match.reference.to_request_summary(),
        )
        self._buffer.record_html(match.html, request_summary=match.request_summary)


class MitmproxyListener:
    """在 MITM 子进程内部用独立线程运行 DumpMaster。"""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        confdir: Path,
        ssl_insecure: bool,
        buffer: CaptureBuffer,
        ready_timeout_seconds: float,
        shutdown_timeout_seconds: float = 3.0,
        monotonic: Any = time.monotonic,
        connect_checker: Any = None,
        thread_factory: Any = Thread,
    ) -> None:
        self._host = host
        self._port = int(port)
        self._confdir = Path(confdir)
        self._ssl_insecure = bool(ssl_insecure)
        self._buffer = buffer
        self._ready_timeout_seconds = float(ready_timeout_seconds)
        self._shutdown_timeout_seconds = float(shutdown_timeout_seconds)
        self._monotonic = monotonic
        self._connect_checker = connect_checker or _can_connect
        self._thread_factory = thread_factory
        self._thread: Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._master: Any | None = None
        self._thread_error: BaseException | None = None
        self._listen_started_at = 0.0
        self._started_once = False

    def start(self) -> float:
        if self._started_once:
            raise MitmproxyListenerError("同一个 MITM 监听器不能重复启动")
        self._started_once = True
        if self._ready_timeout_seconds <= 0:
            raise MitmproxyListenerError("MITM READY 超时必须大于 0")
        if self._connect_checker(self._host, self._port):
            raise MitmproxyListenerError(f"MITM 端口已被占用：{self._host}:{self._port}")

        self._confdir.mkdir(parents=True, exist_ok=True)
        # 请求回调也使用 time.monotonic()；监听起点必须处于同一时钟域。
        self._listen_started_at = float(self._monotonic())
        self._thread = self._thread_factory(
            target=self._thread_main,
            name="awa-mitm-listener",
            daemon=True,
        )
        self._thread.start()

        deadline = self._monotonic() + self._ready_timeout_seconds
        while self._monotonic() < deadline:
            if self._thread_error is not None:
                self.stop()
                raise MitmproxyListenerError(f"MITM 监听启动失败：{self._thread_error}")
            if self._thread is not None and not self._thread.is_alive():
                raise MitmproxyListenerError("MITM 监听线程在 READY 前退出")
            if self._connect_checker(self._host, self._port):
                return self._listen_started_at
            time.sleep(0.02)

        self.stop()
        raise MitmproxyListenerError(
            f"等待 MITM 监听端口超时：{self._host}:{self._port}"
        )

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        if thread.is_alive() and self._loop is not None and self._master is not None:
            try:
                self._loop.call_soon_threadsafe(self._master.shutdown)
            except RuntimeError:
                pass
        thread.join(max(0.0, self._shutdown_timeout_seconds))
        if thread.is_alive():
            raise MitmproxyListenerError("MITM 监听线程未在截止时间内退出")
        self._thread = None
        if self._thread_error is not None:
            error = self._thread_error
            self._thread_error = None
            raise MitmproxyListenerError(f"MITM 监听线程异常：{error}") from error

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._serve())
        except BaseException as exc:
            self._thread_error = exc

    async def _serve(self) -> None:
        from mitmproxy import options
        from mitmproxy.tools.dump import DumpMaster

        self._loop = asyncio.get_running_loop()
        opts = options.Options(
            listen_host=self._host,
            listen_port=self._port,
            confdir=str(self._confdir),
            ssl_insecure=self._ssl_insecure,
        )
        master = DumpMaster(opts, with_termlog=False, with_dumper=False)
        self._master = master
        master.addons.add(
            WechatArticleCaptureAddon(
                buffer=self._buffer,
                matcher=WechatRequestMatcher(listen_started_at=self._listen_started_at),
            )
        )
        await master.run()


def _headers_mapping(headers: Any) -> dict[str, str]:
    if headers is None:
        return {}
    try:
        items = headers.items()
    except Exception:
        return {}
    return {str(key): str(value) for key, value in items}


def _set_header(headers: Any, name: str, value: str) -> None:
    if headers is None:
        return
    try:
        headers[name] = value
    except Exception:
        return


def _can_connect(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.1):
            return True
    except OSError:
        return False
