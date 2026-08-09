from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TASK_METHOD_DIR = Path(__file__).resolve().parent
for candidate in (PROJECT_ROOT, TASK_METHOD_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


def configure_stdio() -> None:
    """统一子进程标准流编码，避免 Windows 控制台输出中文乱码。"""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except Exception:
                pass


def read_payload_from_stdin() -> dict[str, Any]:
    """从 stdin 读取 JSON payload；空输入时返回空字典，便于直接运行脚本。"""
    configure_stdio()
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    data = json.loads(raw)
    if not isinstance(data, Mapping):
        raise ValueError("worker stdin payload 必须是 JSON 对象")
    return dict(data)


def write_result_to_stdout(result: Mapping[str, Any]) -> None:
    """只向 stdout 输出一份 JSON，方便主流程用 subprocess 捕获。"""
    configure_stdio()
    print(json.dumps(to_jsonable(dict(result)), ensure_ascii=False, indent=2))


def base_result(
    *,
    task_id: str,
    attempt_id: str,
    stage: str,
    ok: bool,
    status: str,
    data: Mapping[str, Any] | None = None,
    error: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """生成统一 worker 结果，所有跨进程字段都保持 JSON 可序列化。"""
    return {
        "ok": bool(ok),
        "task_id": str(task_id),
        "attempt_id": str(attempt_id),
        "stage": str(stage),
        "status": str(status),
        "data": to_jsonable(dict(data or {})),
        "error": to_jsonable(dict(error or {})),
    }


def success_result(
    *,
    task_id: str,
    attempt_id: str,
    stage: str,
    status: str = "success",
    data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return base_result(
        task_id=task_id,
        attempt_id=attempt_id,
        stage=stage,
        ok=True,
        status=status,
        data=data,
    )


def skipped_result(
    *,
    task_id: str,
    attempt_id: str,
    stage: str,
    reason: str,
    data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {"reason": reason, **dict(data or {})}
    return base_result(
        task_id=task_id,
        attempt_id=attempt_id,
        stage=stage,
        ok=True,
        status="skipped",
        data=payload,
    )


def failure_result(
    *,
    task_id: str,
    attempt_id: str,
    stage: str,
    message: str,
    code: str = "worker_failed",
    data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return base_result(
        task_id=task_id,
        attempt_id=attempt_id,
        stage=stage,
        ok=False,
        status="failed",
        data=data,
        error={"code": code, "message": message},
    )


def not_implemented_result(
    *,
    task_id: str,
    attempt_id: str,
    stage: str,
    message: str,
) -> dict[str, Any]:
    return base_result(
        task_id=task_id,
        attempt_id=attempt_id,
        stage=stage,
        ok=False,
        status="not_implemented",
        error={"code": "not_implemented", "message": message},
    )


def describe_result(
    *,
    task_id: str,
    attempt_id: str,
    stage: str,
    summary: str,
    actions: list[str],
    safety: str,
) -> dict[str, Any]:
    return success_result(
        task_id=task_id,
        attempt_id=attempt_id,
        stage=stage,
        status="described",
        data={
            "summary": summary,
            "actions": actions,
            "safety": safety,
        },
    )


def run_main(run_worker: Callable[[dict[str, Any]], dict[str, Any]]) -> int:
    """worker 脚本入口；异常也按统一 JSON 协议返回。"""
    configure_stdio()
    try:
        payload = read_payload_from_stdin()
        result = run_worker(payload)
    except Exception as exc:
        result = failure_result(
            task_id="",
            attempt_id="",
            stage="unknown",
            code="worker_exception",
            message=f"{type(exc).__name__}: {exc}",
        )
    write_result_to_stdout(result)
    return 0 if bool(result.get("ok")) else 1


def payload_text(payload: Mapping[str, Any], key: str, default: str = "") -> str:
    value = payload.get(key, default)
    return str(value if value is not None else default)


def payload_int(payload: Mapping[str, Any], key: str, default: int) -> int:
    value = payload.get(key, default)
    return int(value)


def payload_float(payload: Mapping[str, Any], key: str, default: float) -> float:
    value = payload.get(key, default)
    return float(value)


def payload_bool(payload: Mapping[str, Any], key: str, default: bool = False) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def require_mapping(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} 必须是 JSON 对象")
    return dict(value)


def to_jsonable(value: Any) -> Any:
    """把 Path、datetime、枚举等对象转换成可安全跨进程序列化的值。"""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    enum_value = getattr(value, "value", None)
    if enum_value is not None and not isinstance(value, (str, bytes, dict, list, tuple)):
        return enum_value
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    return value
