from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

_TASK_METHOD_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TASK_METHOD_DIR.parents[1]
for _candidate in (_PROJECT_ROOT, _TASK_METHOD_DIR):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from worker_protocol import describe_result, not_implemented_result, run_main


STAGE = "comment_collect"


def run_worker(payload: dict[str, Any]) -> dict[str, Any]:
    task_id = str(payload.get("task_id", ""))
    attempt_id = str(payload.get("attempt_id", ""))
    action = str(payload.get("action", "describe"))
    if action == "describe":
        return describe_result(
            task_id=task_id,
            attempt_id=attempt_id,
            stage=STAGE,
            summary="根据文章保存结果采集评论分页、回复和评论资源，后续接入现有归档与 SQLite 事务。",
            actions=["describe", "collect_comments"],
            safety="当前阶段只声明协议，不伪造评论采集成功。",
        )
    return not_implemented_result(
        task_id=task_id,
        attempt_id=attempt_id,
        stage=STAGE,
        message="评论采集 worker 的真实业务实现待接入。",
    )


def main() -> int:
    return run_main(run_worker)


if __name__ == "__main__":
    raise SystemExit(main())
