from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.core.config import LOG_DIR
from tests.tools.article_detail_probe import probe_from_request_context


CONFIG = {
    # 测试阶段手动改这里即可，不接入主采集流程。
    "request_context_path": "",
    "timeout_seconds": 10.0,
    "output_dir": str(LOG_DIR / "article_detail_probe"),
}


def main() -> None:
    request_context_path = Path(str(CONFIG["request_context_path"] or "")).expanduser()
    if not request_context_path.is_file():
        raise SystemExit(
            "请先在 CONFIG['request_context_path'] 中填写 original_request.json 或 MITM 请求上下文 JSON 路径。"
        )

    report = probe_from_request_context(
        request_context_path,
        timeout_seconds=float(CONFIG.get("timeout_seconds") or 10.0),
    )
    output_dir = Path(str(CONFIG["output_dir"]))
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"article_detail_probe_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"诊断完成：{output_path}")
    print(json.dumps({"metrics": report.get("metrics"), "output_path": str(output_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
