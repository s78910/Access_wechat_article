from __future__ import annotations

import socket
import time

from src.app.fastapi_app import DEFAULT_API_HOST, DEFAULT_API_PORT, FastApiServer
from src.app.pywebview_app.webview_api import WebviewApi
from src.config.runtime_config import load_runtime_config


def create_dev_server(
    load_config=load_runtime_config,
    api_factory=WebviewApi,
    server_factory=FastApiServer,
):
    """按 custom.yaml 创建开发阶段 FastAPI 服务和共享 API 对象。"""
    runtime_config = load_config()
    api = api_factory(
        runtime_config=runtime_config,
        auto_start=runtime_config.app.auto_start_proxy,
        auto_cleanup=True,
    )
    server = server_factory(
        api=api,
        host=DEFAULT_API_HOST,
        port=DEFAULT_API_PORT,
    )
    return server, api


def shutdown_dev_server(server, api) -> None:
    """退出开发服务时先停止 API 服务，再恢复 MITM/系统代理等运行状态。"""
    try:
        if server is not None:
            server.stop()
    finally:
        if api is not None:
            api.shutdown()


def ensure_dev_server_port_available(host: str = DEFAULT_API_HOST, port: int = DEFAULT_API_PORT) -> None:
    """启动前检查 API 端口，避免多个开发后端拆散任务队列和 MITM 捕获队列。"""
    address = (host, int(port))
    try:
        with socket.create_connection(address, timeout=0.2):
            raise RuntimeError(
                f"FastAPI 开发服务端口已被占用：{host}:{port}。"
                "请先停止旧的 dev_server.py，再重新启动，避免前端任务和 MITM 捕获队列不在同一进程。"
            )
    except ConnectionRefusedError:
        pass
    except TimeoutError:
        pass
    except OSError:
        pass

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(address)
    except OSError as exc:
        raise RuntimeError(
            f"FastAPI 开发服务端口已被占用：{host}:{port}。"
            "请先停止旧的 dev_server.py，再重新启动，避免前端任务和 MITM 捕获队列不在同一进程。"
        ) from exc
    finally:
        probe.close()


def main() -> None:
    """开发阶段 FastAPI 后端入口：不打开 pywebview 窗口，供 Chrome/Vite 直接调用。"""
    server = None
    api = None
    try:
        ensure_dev_server_port_available()
        server, api = create_dev_server()
        server.start()
        print(f"AWA FastAPI 开发服务已启动：{server.url}")
        print("API 文档地址：http://127.0.0.1:8766/docs")
        print("按 Ctrl+C 停止本地开发 API，停止时会恢复 MITM/系统代理状态。")
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        shutdown_dev_server(server, api)


if __name__ == "__main__":
    main()
