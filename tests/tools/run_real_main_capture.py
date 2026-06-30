from __future__ import annotations

import json
import sqlite3
import socket
import sys
import time
from datetime import datetime
from multiprocessing import freeze_support
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.pywebview_app.webview_api import WebviewApi
from src.config.runtime_config import load_runtime_config
from src.modules.proxy.system_proxy import WindowsSystemProxy


RECORD_LIMIT = 20
POLL_SECONDS = 2.0
MAX_WAIT_SECONDS = 900.0
ARTIFACT_DIR = PROJECT_ROOT / "tests/artifacts/main_flow_capture"


def main() -> int:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now()
    artifact_path = ARTIFACT_DIR / f"main_capture_{started_at.strftime('%Y%m%d_%H%M%S')}.json"

    system_proxy = WindowsSystemProxy()
    original_proxy = system_proxy.read_current()
    runtime_config = load_runtime_config()
    before_counts = _read_db_counts(runtime_config.storage.db_path)

    result: dict[str, Any] = {
        "startedAt": started_at.isoformat(timespec="seconds"),
        "recordLimit": RECORD_LIMIT,
        "dbPath": str(runtime_config.storage.db_path),
        "proxy": {
            "original": _proxy_to_dict(original_proxy),
            "configured": f"{runtime_config.proxy.host}:{runtime_config.proxy.port}",
            "autoStartProxy": runtime_config.app.auto_start_proxy,
            "enableSystemProxy": runtime_config.proxy.enable_system_proxy,
        },
        "beforeCounts": before_counts,
        "polls": [],
        "logs": [],
        "errors": [],
    }

    api: WebviewApi | None = None
    exit_code = 0
    try:
        api = WebviewApi(runtime_config=runtime_config, auto_start=True, auto_cleanup=False)
        result["proxy"]["afterAutoStart"] = _proxy_to_dict(system_proxy.read_current())

        payload = {
            "recordLimit": RECORD_LIMIT,
            "selections": {"articleDetail": True},
        }
        start_payload = _parse_json(api.start_task(payload))
        result["startPayload"] = start_payload
        print(json.dumps({"event": "started", "payload": start_payload}, ensure_ascii=False))
        if not start_payload.get("ok", False):
            exit_code = 2
            return exit_code

        deadline = time.monotonic() + MAX_WAIT_SECONDS
        last_printed_second = -1
        while True:
            status_payload = _parse_json(api.get_task_status())
            workers = status_payload.get("workers") if isinstance(status_payload.get("workers"), list) else []
            status = str(status_payload.get("status") or "")
            elapsed = round((datetime.now() - started_at).total_seconds(), 1)
            poll = {
                "elapsedSeconds": elapsed,
                "status": status,
                "workers": workers,
                "auth": status_payload.get("auth"),
                "traffic": status_payload.get("traffic"),
                "home": status_payload.get("home"),
            }
            result["polls"].append(poll)

            current_second = int(elapsed)
            if current_second // 10 != last_printed_second // 10:
                last_printed_second = current_second
                print(json.dumps({"event": "poll", **poll}, ensure_ascii=False))

            if status in {"stopped", "error"} and "article_capture" not in workers:
                break
            if time.monotonic() >= deadline:
                result["timeout"] = True
                result["stopPayload"] = _parse_json(api.stop_task())
                exit_code = 3
                break
            time.sleep(POLL_SECONDS)

        result["finalStatus"] = _parse_json(api.get_task_status())
        result["logs"] = _parse_json(api.get_task_logs(300))
        if str(result["finalStatus"].get("status") or "") == "error":
            exit_code = 4
    except Exception as exc:
        result["errors"].append({"type": type(exc).__name__, "message": str(exc)})
        exit_code = 1
    finally:
        if api is not None:
            try:
                api.shutdown()
            except Exception as exc:
                result["errors"].append({"type": type(exc).__name__, "message": f"shutdown failed: {exc}"})
                exit_code = exit_code or 5

        restored_proxy = system_proxy.read_current()
        if _proxy_to_dict(restored_proxy) != _proxy_to_dict(original_proxy):
            try:
                system_proxy.restore(original_proxy)
                result["proxy"]["forcedRestore"] = True
            except Exception as exc:
                result["errors"].append({"type": type(exc).__name__, "message": f"proxy restore failed: {exc}"})
                exit_code = exit_code or 6
        result["proxy"]["afterShutdown"] = _proxy_to_dict(system_proxy.read_current())

        result["afterCounts"] = _read_db_counts(runtime_config.storage.db_path)
        result["mitmPortListeningAfterShutdown"] = _tcp_port_open(runtime_config.proxy.host, runtime_config.proxy.port)
        result["finishedAt"] = datetime.now().isoformat(timespec="seconds")
        result["artifactPath"] = str(artifact_path.resolve())
        artifact_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"event": "finished", "exitCode": exit_code, "artifactPath": result["artifactPath"]}, ensure_ascii=False))

    return exit_code


def _parse_json(value: Any) -> dict[str, Any] | list[Any]:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return {"raw": str(value)}


def _proxy_to_dict(snapshot: Any) -> dict[str, Any]:
    return {
        "enabled": bool(getattr(snapshot, "enabled", False)),
        "server": str(getattr(snapshot, "server", "")),
        "readable": bool(getattr(snapshot, "readable", True)),
        "readError": str(getattr(snapshot, "read_error", "")),
    }


def _read_db_counts(db_path: Path) -> dict[str, Any]:
    if not Path(db_path).exists():
        return {"exists": False, "accounts": 0, "articles": 0, "recent": []}
    with sqlite3.connect(str(db_path)) as conn:
        accounts = int(conn.execute("SELECT COUNT(*) FROM awa_public_accounts").fetchone()[0] or 0)
        articles = int(conn.execute("SELECT COUNT(*) FROM awa_public_articles").fetchone()[0] or 0)
        recent_rows = conn.execute(
            """
            SELECT account.account_name, article.article_title, article.collect_status, article.collect_time
            FROM awa_public_articles AS article
            JOIN awa_public_accounts AS account ON account.id = article.account_id
            ORDER BY article.collect_time DESC, article.id DESC
            LIMIT 30
            """
        ).fetchall()
    return {
        "exists": True,
        "accounts": accounts,
        "articles": articles,
        "recent": [
            {
                "accountName": str(row[0] or ""),
                "title": str(row[1] or ""),
                "status": str(row[2] or ""),
                "collectTime": str(row[3] or ""),
            }
            for row in recent_rows
        ],
    }


def _tcp_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((str(host or "127.0.0.1"), int(port)), timeout=0.3):
            return True
    except OSError:
        return False


if __name__ == "__main__":
    freeze_support()
    raise SystemExit(main())
