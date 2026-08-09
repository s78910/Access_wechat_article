from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from threading import RLock
import time
from typing import Any, Mapping, Protocol
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.main_orchestrator import load_application_runtime
from src.domain.enums import CaptureType, TaskStatus
from src.domain.models import MitmCaptureResult
from src.modules.proxy.wechat_request_matcher import (
    SENSITIVE_QUERY_KEYS,
    redact_sensitive_url,
)
from src.services.capture.mitm_process_control_service import (
    MitmProcessError,
)
from src.services.capture.single_article_capture_service import SingleCaptureSettings


CONFIG: dict[str, Any] = {
    # 直接运行本文件时会真实启停系统代理；设为 False 可只检查配置和输出路径�?    "execute_capture": True,
    "record_index": 1,
    "article_title": "手动单篇 MITM 抓取",
    # 所有测试产物固定写�?tests/output，不生成 _1、_2 目录�?    "output_root": PROJECT_ROOT / "tests" / "output",
}


class AttemptHandle(Protocol):
    def wait_ready(self, *, timeout_seconds: float) -> dict[str, Any]: ...

    def stop_capture(self, *, timeout_seconds: float) -> MitmCaptureResult: ...

    def cancel(self) -> None: ...


class ProcessControl(Protocol):
    def start_attempt(self, **kwargs: Any) -> AttemptHandle: ...


class MitmTaskOutputStore:
    """保存人工 MITM 任务产物；原始证据与脱敏汇总分开存放�?""

    def __init__(self, output_root: str | Path) -> None:
        self.output_root = Path(output_root).resolve()
        self.capture_root = self.output_root / "mitm_capture"
        self.manifest_path = self.output_root / "mitm_capture_records.json"
        self._task_id = ""
        self._records: dict[int, dict[str, Any]] = {}
        self._lock = RLock()

    def reset(self, *, task_id: str) -> None:
        """开始新任务时覆盖汇总；旧的编号目录只会被同编号新结果覆盖�?""
        normalized_task_id = str(task_id).strip()
        if not normalized_task_id:
            raise ValueError("task_id 不能为空")
        with self._lock:
            self.output_root.mkdir(parents=True, exist_ok=True)
            self.capture_root.mkdir(parents=True, exist_ok=True)
            self._task_id = normalized_task_id
            self._records.clear()
            self._write_manifest()

    def write_result(
        self,
        *,
        record_index: int,
        article_title: str,
        result: MitmCaptureResult,
        started_time: str,
        ready_time: str,
        finished_time: str,
        ready_duration_seconds: float,
        capture_duration_seconds: float,
        total_duration_seconds: float,
    ) -> dict[str, Any]:
        with self._lock:
            self._require_reset()
            article_dir = self._article_dir(record_index)
            article_dir.mkdir(parents=True, exist_ok=True)
            html_path = article_dir / "original_main.html"
            request_path = article_dir / "original_request.json"

            if result.html is not None:
                html_path.write_text(result.html, encoding="utf-8")
            else:
                _unlink_generated_file(html_path)

            if result.reference is not None:
                # 原始 reference 只落本地证据文件，不写入控制台和汇总清单�?                request_path.write_text(
                    json.dumps(
                        {
                            "task_id": result.task_id,
                            "attempt_id": result.attempt_id,
                            "reference": result.reference,
                            "request_summary": result.request_summary,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            else:
                _unlink_generated_file(request_path)

            record = {
                "record_index": int(record_index),
                "article_title": str(article_title),
                "task_id": result.task_id,
                "attempt_id": result.attempt_id,
                "status": result.status.value,
                "capture_type": result.capture_type.value,
                "started_time": started_time,
                "ready_time": ready_time,
                "finished_time": finished_time,
                "ready_duration_seconds": round(float(ready_duration_seconds), 3),
                "capture_duration_seconds": round(float(capture_duration_seconds), 3),
                "total_duration_seconds": round(float(total_duration_seconds), 3),
                "html_bytes": _html_bytes(result.html),
                "html_sha256": _html_sha256(result.html),
                "request_summary": _sanitize_summary(result.request_summary),
                "error_stage": result.error_stage,
                "error_message": result.error_message,
                "output_dir": str(article_dir),
                "html_path": str(html_path) if result.html is not None else "",
                "request_path": str(request_path) if result.reference is not None else "",
            }
            self._write_record(article_dir, record)
            return self._upsert_manifest(record_index, record)

    def write_cancelled(
        self,
        *,
        record_index: int,
        article_title: str,
        task_id: str,
        attempt_id: str,
        started_time: str,
        finished_time: str,
        total_duration_seconds: float,
        reason: str,
    ) -> dict[str, Any]:
        with self._lock:
            self._require_reset()
            article_dir = self._article_dir(record_index)
            article_dir.mkdir(parents=True, exist_ok=True)
            _unlink_generated_file(article_dir / "original_main.html")
            _unlink_generated_file(article_dir / "original_request.json")
            record = {
                "record_index": int(record_index),
                "article_title": str(article_title),
                "task_id": str(task_id),
                "attempt_id": str(attempt_id),
                "status": TaskStatus.CANCELLED.value,
                "capture_type": CaptureType.NONE.value,
                "started_time": started_time,
                "ready_time": "",
                "finished_time": finished_time,
                "ready_duration_seconds": 0.0,
                "capture_duration_seconds": 0.0,
                "total_duration_seconds": round(float(total_duration_seconds), 3),
                "html_bytes": 0,
                "html_sha256": "",
                "request_summary": {},
                "error_stage": "cancelled",
                "error_message": str(reason),
                "output_dir": str(article_dir),
                "html_path": "",
                "request_path": "",
            }
            self._write_record(article_dir, record)
            return self._upsert_manifest(record_index, record)

    def _article_dir(self, record_index: int) -> Path:
        index = int(record_index)
        if index <= 0:
            raise ValueError("record_index 必须大于 0")
        return self.capture_root / f"article_{index:03d}"

    def _upsert_manifest(
        self,
        record_index: int,
        record: Mapping[str, Any],
    ) -> dict[str, Any]:
        stored = dict(record)
        self._records[int(record_index)] = stored
        self._write_manifest()
        return stored

    def _write_record(self, article_dir: Path, record: Mapping[str, Any]) -> None:
        (article_dir / "capture_result.json").write_text(
            json.dumps(dict(record), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_manifest(self) -> None:
        payload = {
            "task_id": self._task_id,
            "output_root": str(self.output_root),
            "record_count": len(self._records),
            "records": [self._records[index] for index in sorted(self._records)],
        }
        self.manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _require_reset(self) -> None:
        if not self._task_id:
            raise RuntimeError("写入 MITM 结果前必须先调用 reset")


class SingleArticleMitmTask:
    """父进程中的单�?MITM 生命周期句柄；一个对象只允许启动一次�?""

    def __init__(
        self,
        *,
        process_control: ProcessControl,
        settings: SingleCaptureSettings,
        output_store: MitmTaskOutputStore,
        task_id: str,
        proxy_lease_id: str,
        attempt_id: str,
        record_index: int,
        article_title: str,
    ) -> None:
        self._process_control = process_control
        self._settings = settings
        self._output_store = output_store
        self.task_id = _require_text(task_id, "task_id")
        self.proxy_lease_id = _require_text(proxy_lease_id, "proxy_lease_id")
        self.attempt_id = _require_text(attempt_id, "attempt_id")
        self.record_index = int(record_index)
        if self.record_index <= 0:
            raise ValueError("record_index 必须大于 0")
        self.article_title = str(article_title)
        self._attempt: AttemptHandle | None = None
        self._started_at = 0.0
        self._ready_at = 0.0
        self._started_time = ""
        self._ready_time = ""
        self._terminal = False

    @property
    def terminal(self) -> bool:
        return self._terminal

    def start(self) -> dict[str, Any]:
        if self._attempt is not None or self._terminal:
            raise RuntimeError("同一个单�?MITM 任务不能重复启动")
        self._started_at = time.monotonic()
        self._started_time = _current_iso_time()
        try:
            self._attempt = self._process_control.start_attempt(
                task_id=self.task_id,
                attempt_id=self.attempt_id,
                proxy_lease_id=self.proxy_lease_id,
                proxy_address=self._settings.proxy_address,
                capture_config=self._settings.capture_config,
            )
            ready = self._attempt.wait_ready(
                timeout_seconds=self._settings.ready_timeout_seconds
            )
            self._ready_at = time.monotonic()
            self._ready_time = _current_iso_time()
            return dict(ready)
        except Exception as exc:
            if self._attempt is not None:
                try:
                    self._attempt.cancel()
                except Exception:
                    pass
            self._terminal = True
            finished_at = time.monotonic()
            self._output_store.write_result(
                record_index=self.record_index,
                article_title=self.article_title,
                result=MitmCaptureResult.failed(
                    task_id=self.task_id,
                    attempt_id=self.attempt_id,
                    error_stage="mitm_ready",
                    error_message=str(exc),
                ),
                started_time=self._started_time,
                ready_time="",
                finished_time=_current_iso_time(),
                ready_duration_seconds=0.0,
                capture_duration_seconds=0.0,
                total_duration_seconds=max(0.0, finished_at - self._started_at),
            )
            raise

    def stop(self) -> dict[str, Any]:
        if self._attempt is None:
            raise RuntimeError("MITM 任务尚未启动")
        if self._terminal:
            raise RuntimeError("MITM 任务已经结束")
        stop_started_at = time.monotonic()
        try:
            result = self._attempt.stop_capture(
                timeout_seconds=self._settings.result_timeout_seconds
            )
        except MitmProcessError as exc:
            result = exc.result or MitmCaptureResult.failed(
                task_id=self.task_id,
                attempt_id=self.attempt_id,
                error_stage="mitm_process",
                error_message=str(exc),
            )
            self._terminal = True
            self._persist_result(result, stop_started_at=stop_started_at)
            raise
        except Exception as exc:
            self._attempt.cancel()
            result = MitmCaptureResult.failed(
                task_id=self.task_id,
                attempt_id=self.attempt_id,
                error_stage="mitm_process",
                error_message=str(exc),
            )
            self._terminal = True
            self._persist_result(result, stop_started_at=stop_started_at)
            raise

        self._terminal = True
        return self._persist_result(result, stop_started_at=stop_started_at)

    def cancel(self, reason: str) -> dict[str, Any] | None:
        if self._terminal:
            return None
        if self._attempt is not None:
            self._attempt.cancel()
        self._terminal = True
        now = time.monotonic()
        return self._output_store.write_cancelled(
            record_index=self.record_index,
            article_title=self.article_title,
            task_id=self.task_id,
            attempt_id=self.attempt_id,
            started_time=self._started_time or _current_iso_time(),
            finished_time=_current_iso_time(),
            total_duration_seconds=(now - self._started_at if self._started_at else 0.0),
            reason=str(reason),
        )

    def _persist_result(
        self,
        result: MitmCaptureResult,
        *,
        stop_started_at: float,
    ) -> dict[str, Any]:
        finished_at = time.monotonic()
        return self._output_store.write_result(
            record_index=self.record_index,
            article_title=self.article_title,
            result=result,
            started_time=self._started_time,
            ready_time=self._ready_time,
            finished_time=_current_iso_time(),
            ready_duration_seconds=(
                self._ready_at - self._started_at if self._ready_at else 0.0
            ),
            capture_duration_seconds=max(0.0, finished_at - stop_started_at),
            total_duration_seconds=max(0.0, finished_at - self._started_at),
        )


def create_attempt_identity(record_index: int) -> tuple[str, str]:
    suffix = uuid4().hex[:12]
    return f"attempt-{int(record_index):03d}-{suffix}", f"proxy-lease-{suffix}"


def main() -> int:
    _configure_stdout()
    task_id = f"manual-mitm-{datetime.now().astimezone():%Y%m%d-%H%M%S}"
    output_store = MitmTaskOutputStore(CONFIG["output_root"])
    output_store.reset(task_id=task_id)

    if not bool(CONFIG["execute_capture"]):
        print(
            json.dumps(
                {
                    "ok": True,
                    "reason": "dry_run_completed",
                    "output_path": str(output_store.manifest_path),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    runtime = load_application_runtime(project_root=PROJECT_ROOT)
    if not runtime.config.proxy.enable_system_proxy:
        raise RuntimeError("custom.yaml 已关�?enable_system_proxy，无法执行真�?MITM 生命周期")

    record_index = int(CONFIG["record_index"])
    attempt_id, proxy_lease_id = create_attempt_identity(record_index)
    task = SingleArticleMitmTask(
        process_control=runtime.capture_factory.create_process_control(),
        settings=runtime.single_capture_settings,
        output_store=output_store,
        task_id=task_id,
        proxy_lease_id=proxy_lease_id,
        attempt_id=attempt_id,
        record_index=record_index,
        article_title=str(CONFIG["article_title"]),
    )

    try:
        ready = task.start()
        print(
            "MITM �?READY，系统代理已接管。请点击并关闭一篇微信文章，"
            "完成后回到终端按回车停止抓取�?
        )
        print(
            json.dumps(
                {
                    "proxy_address": ready.get("proxy_address", ""),
                    "attempt_id": attempt_id,
                },
                ensure_ascii=False,
            )
        )
        input()
        record = task.stop()
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0 if record["status"] == TaskStatus.SUCCESS.value else 3
    except KeyboardInterrupt:
        task.cancel("用户中断单篇 MITM 人工任务")
        return 130
    except Exception as exc:
        task.cancel(f"单篇 MITM 人工任务异常：{exc}")
        print(f"执行失败：{exc}")
        return 3


def _sanitize_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key)
        lowered = key.lower()
        if lowered in SENSITIVE_QUERY_KEYS or lowered in {"cookie", "request_headers", "headers"}:
            continue
        if isinstance(raw_value, Mapping):
            result[key] = _sanitize_summary(raw_value)
        elif isinstance(raw_value, list):
            result[key] = [
                _sanitize_summary(item) if isinstance(item, Mapping) else item
                for item in raw_value
            ]
        elif isinstance(raw_value, str) and "url" in lowered:
            result[key] = redact_sensitive_url(raw_value)
        else:
            result[key] = raw_value
    return result


def _html_bytes(html: str | None) -> int:
    return len(html.encode("utf-8")) if html is not None else 0


def _html_sha256(html: str | None) -> str:
    if html is None:
        return ""
    return hashlib.sha256(html.encode("utf-8")).hexdigest()


def _unlink_generated_file(path: Path) -> None:
    if path.is_file():
        path.unlink()


def _require_text(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} 不能为空")
    return normalized


def _current_iso_time() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _configure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
