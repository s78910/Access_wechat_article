from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from typing import Any

_TASK_METHOD_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TASK_METHOD_DIR.parents[1]
for _candidate in (_PROJECT_ROOT, _TASK_METHOD_DIR):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from worker_protocol import (
    PROJECT_ROOT,
    describe_result,
    failure_result,
    payload_float,
    require_mapping,
    run_main,
    success_result,
)


STAGE = "html_parse_save"


def run_worker(payload: dict[str, Any]) -> dict[str, Any]:
    task_id = str(payload.get("task_id", ""))
    attempt_id = str(payload.get("attempt_id", ""))
    action = str(payload.get("action", "describe"))
    if action == "describe":
        return describe_result(
            task_id=task_id,
            attempt_id=attempt_id,
            stage=STAGE,
            summary="接收标准 MITM 捕获结果，解析微信文�?HTML/reference，并按现有归档服务写�?SQLite 与本地资源�?,
            actions=["describe", "save_capture"],
            safety="缺少 capture_result、target �?context 时直接失败，不伪造保存成功�?,
        )
    if action != "save_capture":
        return failure_result(
            task_id=task_id,
            attempt_id=attempt_id,
            stage=STAGE,
            code="unknown_action",
            message=f"未知 HTML 解析保存动作：{action}",
        )
    try:
        return _save_capture(payload, task_id=task_id, attempt_id=attempt_id)
    except Exception as exc:
        return failure_result(
            task_id=task_id,
            attempt_id=attempt_id,
            stage=STAGE,
            code="html_parse_save_failed",
            message=f"{type(exc).__name__}: {exc}",
        )


def _save_capture(
    payload: dict[str, Any],
    *,
    task_id: str,
    attempt_id: str,
) -> dict[str, Any]:
    from src.app.main_orchestrator import load_application_runtime
    from src.domain.models import ArticleTarget, MitmCaptureResult, TaskContext
    from src.services.capture.html_parse_save_service import HtmlParseSaveService

    context_payload = require_mapping(payload, "context")
    target_payload = require_mapping(payload, "target")
    capture_payload = require_mapping(payload, "capture_result")

    runtime = load_application_runtime(project_root=PROJECT_ROOT)
    context = TaskContext(
        task_id=str(context_payload.get("task_id") or task_id),
        proxy_lease_id=str(context_payload.get("proxy_lease_id", "")),
        db_path=Path(context_payload.get("db_path") or runtime.config.storage.database_path),
        storage_root=Path(
            context_payload.get("storage_root") or runtime.config.storage.article_storage_root
        ),
        temp_dir=Path(context_payload.get("temp_dir") or runtime.config.storage.temp_dir),
        started_at=_parse_datetime(context_payload.get("started_at")),
    )
    target = ArticleTarget(
        account_name=str(target_payload.get("account_name", "")),
        title=str(target_payload.get("title", "")),
        click_x=int(target_payload.get("click_x", 0)),
        click_y=int(target_payload.get("click_y", 0)),
        home_window_handle=int(target_payload.get("home_window_handle", 0)),
        fingerprint=str(target_payload.get("fingerprint", "")),
    )
    capture_result = MitmCaptureResult.from_dict(
        {
            **capture_payload,
            "task_id": str(capture_payload.get("task_id") or task_id),
            "attempt_id": str(capture_payload.get("attempt_id") or attempt_id),
        }
    )
    result = HtmlParseSaveService().save(
        context=context,
        target=target,
        capture_result=capture_result,
        attempt_started_at=_parse_datetime(payload.get("attempt_started_at")),
        duration_seconds=payload_float(payload, "duration_seconds", 0.0),
        request_timeout_seconds=float(runtime.config.request.request_timeout_seconds),
    )
    if not result.status.value == "success":
        return failure_result(
            task_id=task_id,
            attempt_id=attempt_id,
            stage=STAGE,
            code=str(result.error_code.value if result.error_code else "save_failed"),
            message=result.message,
        )
    data = result.data
    return success_result(
        task_id=task_id,
        attempt_id=attempt_id,
        stage=STAGE,
        data={
            "article_id": data.article_id,
            "account_id": data.account_id,
            "history_id": data.history_id,
            "article_directory": str(data.article_directory),
            "archive_dir": data.archive_dir,
            "detail_path": str(data.detail_path),
            "resource_types": data.resource_manifest.to_json_values(),
            "html_source": data.html_source,
        },
    )


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return datetime.now()


def main() -> int:
    return run_main(run_worker)


if __name__ == "__main__":
    raise SystemExit(main())
