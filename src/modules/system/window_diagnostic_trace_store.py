from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from threading import Lock
from typing import Any


_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class WindowDiagnosticTraceStore:
    """在配置的临时目录内保存窗口读取诊断的完整过程和最终结果。"""

    def __init__(self, *, temp_root: Path, job_id: str) -> None:
        normalized_job_id = str(job_id).strip()
        if not _JOB_ID_PATTERN.fullmatch(normalized_job_id):
            raise ValueError("窗口诊断任务 ID 含有非法字符")

        self._temp_root = Path(temp_root).resolve()
        self.trace_dir = (
            self._temp_root / "window-click-flow" / normalized_job_id
        ).resolve()
        if not self.trace_dir.is_relative_to(self._temp_root):
            raise ValueError("窗口诊断记录目录超出临时目录")

        self.trace_dir.mkdir(parents=True, exist_ok=True)
        self.execution_log_path = self.trace_dir / "execution.jsonl"
        self.result_path = self.trace_dir / "result.json"
        self._lock = Lock()
        self._sequence = self._last_sequence()

    def append_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """追加单条 JSONL 记录；原始 UIA 详情和候选判定保持不删减。"""

        with self._lock:
            self._sequence += 1
            payload = dict(event)
            payload["sequence"] = self._sequence
            payload.setdefault("recordedAt", _now_iso())
            payload.setdefault("event", str(payload.get("kind", "diagnostic-event")))
            payload.setdefault("status", str(payload.get("tone", "info")))
            payload.setdefault(
                "message",
                str(payload.get("value") or payload.get("label") or ""),
            )
            payload.setdefault("details", {})
            payload.setdefault("decisions", [])
            serialized = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            )
            with self.execution_log_path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(serialized)
                stream.write("\n")
            return payload

    def write_result(self, result: dict[str, Any]) -> None:
        """先写同目录临时文件，再原子替换最终结果，避免留下半份 JSON。"""

        payload = dict(result)
        payload.setdefault("recordedAt", _now_iso())
        temporary_path = self.trace_dir / "result.json.tmp"
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        with self._lock:
            temporary_path.write_text(serialized + "\n", encoding="utf-8")
            temporary_path.replace(self.result_path)

    def path_fields(self) -> dict[str, str]:
        return {
            "traceDir": str(self.trace_dir),
            "executionLogPath": str(self.execution_log_path),
            "resultPath": str(self.result_path),
        }

    def _last_sequence(self) -> int:
        if not self.execution_log_path.is_file():
            return 0
        try:
            lines = self.execution_log_path.read_text(encoding="utf-8").splitlines()
            if not lines:
                return 0
            value = json.loads(lines[-1]).get("sequence", 0)
            return max(0, int(value))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return 0


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


__all__ = ["WindowDiagnosticTraceStore"]
