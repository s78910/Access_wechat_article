from __future__ import annotations

from typing import Any
from urllib import request


DEFAULT_HTTPS_TEST_URL = "https://www.baidu.com/"


def test_https_proxy_connection(
    host: str,
    port: int,
    url: str = DEFAULT_HTTPS_TEST_URL,
    timeout: float = 5,
    opener: Any | None = None,
) -> dict:
    """通过本机代理访问 HTTPS 页面，验证 HTTPS 内容是否能被获取。"""
    proxy_url = f"http://{host}:{int(port)}"
    safe_url = url if str(url).lower().startswith("https://") else DEFAULT_HTTPS_TEST_URL
    http_opener = opener or request.build_opener(
        request.ProxyHandler(
            {
                "http": proxy_url,
                "https": proxy_url,
            }
        )
    )
    probe_request = request.Request(
        safe_url,
        headers={
            "User-Agent": "AccessWechatArticle/1.0 HTTPS probe",
        },
    )

    try:
        with http_opener.open(probe_request, timeout=timeout) as response:
            body = response.read(4096)
            status_code = int(response.getcode() or 0)
    except Exception as exc:
        return {
            "ok": False,
            "status": "failed",
            "message": f"HTTPS 代理测试失败：{exc}",
            "url": safe_url,
            "proxy": proxy_url,
            "statusCode": 0,
            "bytesRead": 0,
        }

    bytes_read = len(body or b"")
    ok = 200 <= status_code < 400 and bytes_read > 0
    return {
        "ok": ok,
        "status": "passed" if ok else "failed",
        "message": "已通过代理获取 HTTPS 测试内容。" if ok else "代理返回异常，未获取到有效 HTTPS 内容。",
        "url": safe_url,
        "proxy": proxy_url,
        "statusCode": status_code,
        "bytesRead": bytes_read,
    }
