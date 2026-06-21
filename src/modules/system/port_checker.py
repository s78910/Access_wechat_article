from __future__ import annotations

import socket


def is_tcp_port_open(host: str, port: int, *, timeout_seconds: float = 0.2) -> bool:
    """检测本机 TCP 端口是否能连接，用于启动服务前判断端口占用。"""
    try:
        with socket.create_connection((host, int(port)), timeout=max(0.01, float(timeout_seconds))):
            return True
    except OSError:
        return False


__all__ = ["is_tcp_port_open"]
