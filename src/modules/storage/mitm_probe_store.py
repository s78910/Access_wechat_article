from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path


DEFAULT_MITM_RESPONSE_INSPECT_SECONDS = 5.0


def write_current_mitm_target_probe(
    path: Path,
    *,
    article_index: int,
    target_title: str,
    inspect_duration_seconds: float = DEFAULT_MITM_RESPONSE_INSPECT_SECONDS,
) -> None:
    """把本轮点击标题写给常驻 MITM 进程做轻量响应匹配诊断。"""
    target = str(target_title or "").strip()
    if not target:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return

    try:
        inspect_seconds = max(0.1, float(inspect_duration_seconds))
    except (TypeError, ValueError):
        inspect_seconds = DEFAULT_MITM_RESPONSE_INSPECT_SECONDS

    now = time.time()
    payload = {
        "article_index": int(article_index),
        "target_title": target,
        "updated_at": now,
        "inspect_until": now + inspect_seconds,
        "inspect_duration_seconds": inspect_seconds,
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


__all__ = ["DEFAULT_MITM_RESPONSE_INSPECT_SECONDS", "write_current_mitm_target_probe"]
