from __future__ import annotations

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
    payload_bool,
    payload_float,
    payload_int,
    run_main,
    skipped_result,
    success_result,
)


STAGE = "mitm_capture"


def run_worker(payload: dict[str, Any]) -> dict[str, Any]:
    task_id = str(payload.get("task_id", ""))
    attempt_id = str(payload.get("attempt_id", ""))
    action = str(payload.get("action", "describe"))
    if action == "describe":
        return describe_result(
            task_id=task_id,
            attempt_id=attempt_id,
            stage=STAGE,
            summary="启动单次 MITM 捕获子进程，等待捕获窗口期结束后冻结并返回 HTML/reference 结果。",
            actions=["describe", "manual_capture_once"],
            safety="除非 execute_capture=true，否则不会启动 MITM 或修改系统代理。",
        )
    if action != "manual_capture_once":
        return failure_result(
            task_id=task_id,
            attempt_id=attempt_id,
            stage=STAGE,
            code="unknown_action",
            message=f"未知 MITM 动作：{action}",
        )
    if not payload_bool(payload, "execute_capture", False):
        return skipped_result(
            task_id=task_id,
            attempt_id=attempt_id,
            stage=STAGE,
            reason="execute_capture_not_enabled",
            data={"action": action},
        )
    try:
        return _manual_capture_once(payload, task_id=task_id, attempt_id=attempt_id)
    except Exception as exc:
        return failure_result(
            task_id=task_id,
            attempt_id=attempt_id,
            stage=STAGE,
            code="mitm_capture_failed",
            message=f"{type(exc).__name__}: {exc}",
        )


def _manual_capture_once(
    payload: dict[str, Any],
    *,
    task_id: str,
    attempt_id: str,
) -> dict[str, Any]:
    from task_method_import_compat import import_task_method_module

    old_mitm = import_task_method_module("b_test_single_mitm_capture.py")
    runtime = __import__(
        "src.app.main_orchestrator",
        fromlist=["load_application_runtime"],
    ).load_application_runtime(project_root=PROJECT_ROOT)
    if not runtime.config.proxy.enable_system_proxy:
        raise RuntimeError("custom.yaml 已关闭 enable_system_proxy，不能执行真实 MITM 生命周期")

    record_index = payload_int(payload, "record_index", 1)
    output_store = old_mitm.MitmTaskOutputStore(
        payload.get("output_root", PROJECT_ROOT / "tests" / "output")
    )
    output_store.reset(task_id=task_id)
    proxy_lease_id = str(payload.get("proxy_lease_id", "")).strip()
    if not proxy_lease_id:
        _, proxy_lease_id = old_mitm.create_attempt_identity(record_index)
    task = old_mitm.SingleArticleMitmTask(
        process_control=runtime.capture_factory.create_process_control(),
        settings=runtime.single_capture_settings,
        output_store=output_store,
        task_id=task_id,
        proxy_lease_id=proxy_lease_id,
        attempt_id=attempt_id,
        record_index=record_index,
        article_title=str(payload.get("article_title", "手动单篇 MITM 捕获")),
    )
    try:
        ready = task.start()
        wait_seconds = max(0.0, payload_float(payload, "capture_wait_seconds", 0.0))
        if wait_seconds:
            import time

            time.sleep(wait_seconds)
        record = task.stop()
        return success_result(
            task_id=task_id,
            attempt_id=attempt_id,
            stage=STAGE,
            status=str(record.get("status", "success")),
            data={
                "ready": ready,
                "record": record,
                "output_path": str(output_store.manifest_path),
            },
        )
    except Exception:
        task.cancel("MITM worker 异常，已取消本次捕获")
        raise


def main() -> int:
    return run_main(run_worker)


if __name__ == "__main__":
    raise SystemExit(main())
