from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, NamedTuple
from uuid import uuid4

_TASK_METHOD_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TASK_METHOD_DIR.parents[1]
for _candidate in (_PROJECT_ROOT, _TASK_METHOD_DIR):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from worker_protocol import (
    PROJECT_ROOT,
    TASK_METHOD_DIR,
    failure_result,
    payload_bool,
    payload_int,
    read_payload_from_stdin,
    skipped_result,
    success_result,
    to_jsonable,
    write_result_to_stdout,
)


CONFIG: dict[str, Any] = {
    # =========================
    # 主任务目标
    # =========================
    # 目标成功采集数量；主流程达到该数量后停止继续尝试。
    "target_success_count": 1,
    # 全局最大尝试次数；包括成功、失败、跳过的 attempt，避免无限循环。
    "max_attempts": 1,
    # 单篇文章额外重试次数预留参数；当前主编排先记录，不在 a_ 内直接执行业务重试。
    "article_retry_count": 0,

    # =========================
    # 后置任务开关
    # =========================
    # 是否在文章保存完成后采集评论；真实逻辑后续由 e_comment_collect_worker.py 接入。
    "collect_comments": False,
    # 是否在文章保存完成后生成离线缓存；真实逻辑后续由 f_offline_cache_worker.py 接入。
    "build_offline_cache": False,

    # =========================
    # 子任务执行开关
    # =========================
    # 是否调用窗口控制 worker：负责识别主页、点击文章、确认并关闭文章标签。
    "run_window_control": True,
    # 是否调用 MITM 捕获 worker：负责启动/停止代理捕获，并返回 HTML 或 reference。
    "run_mitm_capture": False,
    # 是否调用 HTML 解析保存 worker：负责解析捕获结果并写入归档文件和 SQLite。
    "run_html_parse_save": False,
    # 是否调用评论采集 worker；当前 worker 只声明协议，不伪造采集成功。
    "run_comment_collect": False,
    # 是否调用离线缓存 worker；当前 worker 只声明协议，不伪造缓存成功。
    "run_offline_cache": False,

    # =========================
    # 安全执行开关
    # =========================
    # 默认 dry-run 只验证编排和协议，避免直接点击微信或修改系统代理。
    "dry_run": False,
    # 只有设为 True，窗口 worker 才会真实点击微信文章并关闭文章标签。
    "execute_click": True,
    # 只有设为 True，MITM worker 才会真实启动代理并修改/恢复系统代理。
    "execute_capture": False,

    # =========================
    # 输出位置
    # =========================
    # worker 调试产物输出目录；默认写入 tests/output，固定覆盖同编号结果。
    "output_root": PROJECT_ROOT / "tests" / "output",
}


class WorkerSpec(NamedTuple):
    stage: str
    file_name: str
    enabled_key: str
    default_action: str


WORKER_SPECS: tuple[WorkerSpec, ...] = (
    WorkerSpec(
        "window_control",
        "b_window_control_worker.py",
        "run_window_control",
        "open_and_close_article",
    ),
    WorkerSpec(
        "mitm_capture",
        "c_mitm_capture_worker.py",
        "run_mitm_capture",
        "manual_capture_once",
    ),
    WorkerSpec(
        "html_parse_save",
        "d_html_parse_save_worker.py",
        "run_html_parse_save",
        "save_capture",
    ),
    WorkerSpec(
        "comment_collect",
        "e_comment_collect_worker.py",
        "run_comment_collect",
        "collect_comments",
    ),
    WorkerSpec(
        "offline_cache",
        "f_offline_cache_worker.py",
        "run_offline_cache",
        "build_offline_cache",
    ),
)


def build_execution_plan(config: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = _merge_config(config)
    enabled_stages = [
        spec.stage
        for spec in WORKER_SPECS
        if bool(merged.get(spec.enabled_key, False))
    ]
    return {
        "target_success_count": int(merged["target_success_count"]),
        "max_attempts": int(merged["max_attempts"]),
        "article_retry_count": int(merged.get("article_retry_count", 0)),
        "enabled_stages": enabled_stages,
        "dry_run": bool(merged.get("dry_run", True)),
    }


def run_orchestrator(config: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = _merge_config(config)
    task_id = str(merged.get("task_id") or _new_task_id())
    plan = build_execution_plan(merged)
    if plan["dry_run"]:
        return success_result(
            task_id=task_id,
            attempt_id="",
            stage="main_orchestrator",
            status="planned",
            data={"plan": plan, "worker_specs": [spec._asdict() for spec in WORKER_SPECS]},
        )

    max_attempts = payload_int(merged, "max_attempts", 1)
    target_success_count = payload_int(merged, "target_success_count", 1)
    results: list[dict[str, Any]] = []
    success_count = 0
    for record_index in range(1, max_attempts + 1):
        attempt_id = str(merged.get("attempt_id") or _new_attempt_id(record_index))
        attempt_results = _run_attempt(
            merged,
            task_id=task_id,
            attempt_id=attempt_id,
            record_index=record_index,
        )
        results.extend(attempt_results)
        if _attempt_saved_successfully(attempt_results):
            success_count += 1
        if success_count >= target_success_count:
            break

    ok = success_count >= target_success_count
    if not ok:
        return failure_result(
            task_id=task_id,
            attempt_id="",
            stage="main_orchestrator",
            code="target_not_reached",
            message=f"目标成功数 {target_success_count}，实际成功数 {success_count}",
            data={"plan": plan, "success_count": success_count, "results": results},
        )
    return success_result(
        task_id=task_id,
        attempt_id="",
        stage="main_orchestrator",
        data={"plan": plan, "success_count": success_count, "results": results},
    )


def _run_attempt(
    config: dict[str, Any],
    *,
    task_id: str,
    attempt_id: str,
    record_index: int,
) -> list[dict[str, Any]]:
    stage_results: list[dict[str, Any]] = []
    previous_data: dict[str, Any] = {}
    for spec in WORKER_SPECS:
        if not bool(config.get(spec.enabled_key, False)):
            continue
        payload = _build_worker_payload(
            config,
            spec=spec,
            task_id=task_id,
            attempt_id=attempt_id,
            record_index=record_index,
            previous_data=previous_data,
        )
        result = _run_worker_subprocess(spec, payload)
        stage_results.append(result)
        previous_data[spec.stage] = result.get("data", {})
        if not bool(result.get("ok")):
            break
    return stage_results


def _build_worker_payload(
    config: dict[str, Any],
    *,
    spec: WorkerSpec,
    task_id: str,
    attempt_id: str,
    record_index: int,
    previous_data: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "task_id": task_id,
        "attempt_id": attempt_id,
        "record_index": record_index,
        "action": spec.default_action,
        "execute_click": payload_bool(config, "execute_click", False),
        "execute_capture": payload_bool(config, "execute_capture", False),
        "output_root": str(Path(config.get("output_root", CONFIG["output_root"])).resolve()),
        "previous_data": previous_data,
    }
    # HTML 保存必须接收明确证据；没有上游捕获结果时让 worker 返回失败，避免伪造保存。
    if spec.stage == "html_parse_save":
        capture_record = (
            previous_data.get("mitm_capture", {})
            .get("record", {})
            if isinstance(previous_data.get("mitm_capture"), dict)
            else {}
        )
        window_data = previous_data.get("window_control", {})
        if isinstance(capture_record, dict):
            payload["capture_result"] = _capture_record_to_result(capture_record)
        if isinstance(window_data, dict) and isinstance(window_data.get("target"), dict):
            payload["target"] = window_data["target"]
        payload["context"] = _default_context_payload(
            task_id=task_id,
            proxy_lease_id=f"proxy-lease-{attempt_id}",
        )
    return payload


def _run_worker_subprocess(spec: WorkerSpec, payload: dict[str, Any]) -> dict[str, Any]:
    worker_path = TASK_METHOD_DIR / spec.file_name
    completed = subprocess.run(
        [sys.executable, str(worker_path)],
        input=json.dumps(to_jsonable(payload), ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=payload_int(payload, "worker_timeout_seconds", 300),
    )
    stdout = completed.stdout.strip()
    if not stdout:
        return failure_result(
            task_id=str(payload.get("task_id", "")),
            attempt_id=str(payload.get("attempt_id", "")),
            stage=spec.stage,
            code="empty_worker_output",
            message=completed.stderr.strip() or "worker 没有输出 JSON 结果",
        )
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return failure_result(
            task_id=str(payload.get("task_id", "")),
            attempt_id=str(payload.get("attempt_id", "")),
            stage=spec.stage,
            code="invalid_worker_json",
            message=f"worker 输出不是有效 JSON：{exc}",
            data={"stdout": stdout, "stderr": completed.stderr.strip()},
        )
    if completed.returncode != 0 and bool(result.get("ok")):
        return failure_result(
            task_id=str(payload.get("task_id", "")),
            attempt_id=str(payload.get("attempt_id", "")),
            stage=spec.stage,
            code="worker_exit_failed",
            message=f"worker 退出码异常：{completed.returncode}",
            data={"result": result, "stderr": completed.stderr.strip()},
        )
    return result


def _capture_record_to_result(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": record.get("task_id", ""),
        "attempt_id": record.get("attempt_id", ""),
        "status": record.get("status", "failed"),
        "capture_type": record.get("capture_type", "none"),
        "html": _read_text_if_exists(record.get("html_path")),
        "reference": _read_reference_if_exists(record.get("request_path")),
        "request_summary": record.get("request_summary", {}),
        "error_stage": record.get("error_stage", ""),
        "error_message": record.get("error_message", ""),
    }


def _default_context_payload(*, task_id: str, proxy_lease_id: str) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "proxy_lease_id": proxy_lease_id,
        "db_path": str(PROJECT_ROOT / "data" / "sql" / "awa-v2.1.sqlite3"),
        "storage_root": str(PROJECT_ROOT / "storages"),
        "temp_dir": str(PROJECT_ROOT / "data" / "tmp" / task_id),
        "started_at": datetime.now().astimezone().isoformat(),
    }


def _attempt_saved_successfully(results: list[dict[str, Any]]) -> bool:
    return any(
        item.get("stage") == "html_parse_save" and item.get("status") == "success"
        for item in results
    )


def _read_text_if_exists(path_value: object) -> str | None:
    path_text = str(path_value or "")
    if not path_text:
        return None
    path = Path(path_text)
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _read_reference_if_exists(path_value: object) -> dict[str, Any] | None:
    path_text = str(path_value or "")
    if not path_text:
        return None
    path = Path(path_text)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    reference = data.get("reference")
    return dict(reference) if isinstance(reference, dict) else None


def _merge_config(config: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(CONFIG)
    if config:
        merged.update(config)
    return merged


def _new_task_id() -> str:
    return f"task-method-{datetime.now().astimezone():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}"


def _new_attempt_id(record_index: int) -> str:
    return f"attempt-{int(record_index):03d}-{uuid4().hex[:12]}"


def main() -> int:
    payload = read_payload_from_stdin()
    if not payload:
        payload = dict(CONFIG)
    result = run_orchestrator(payload)
    write_result_to_stdout(result)
    return 0 if bool(result.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
