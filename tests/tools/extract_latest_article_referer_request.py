from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from src.core.config import LOG_DIR


CONFIG = {
    # 为空时自动读取今天 tmp 日期目录下最新的 .log。
    "log_path": "",
    "output_path": str(LOG_DIR / "article_capture" / "latest_referer_request_context.json"),
}


def main() -> None:
    log_path = resolve_log_path()
    text = log_path.read_text(encoding="utf-8", errors="ignore")
    url = extract_latest_referer_url(text)
    if not url:
        raise SystemExit(f"未从日志中找到 article_referer_seen URL：{log_path}")

    output_path = Path(str(CONFIG["output_path"]))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "method": "GET",
        "request_url": url,
        "request_headers": {
            # 这里不是原始完整 headers，只用于测试 referer URL 能否被服务端接受。
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "KHTML, like Gecko MicroMessenger/3.9.0"
            ),
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "referer": url,
        },
        "source": "runtime_log_article_referer_seen",
        "createdAt": datetime.now().isoformat(timespec="seconds"),
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成请求上下文：{output_path}")
    print(url)


def resolve_log_path() -> Path:
    configured = str(CONFIG.get("log_path") or "").strip()
    if configured:
        path = Path(configured)
        if path.is_file():
            return path
        raise SystemExit(f"日志文件不存在：{path}")
    candidates = sorted(LOG_DIR.glob("20*/**/*.log"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not candidates:
        raise SystemExit(f"未找到运行日志：{LOG_DIR}")
    return candidates[0]


def extract_latest_referer_url(text: str) -> str:
    pattern = r"article_referer_seen\s+(https://[^\s\"']+)"
    matches = re.findall(pattern, str(text or ""))
    return matches[-1] if matches else ""


if __name__ == "__main__":
    main()
