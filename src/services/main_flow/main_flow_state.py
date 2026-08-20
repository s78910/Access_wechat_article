from __future__ import annotations

from datetime import datetime
from threading import RLock
from typing import Any, Callable

from .main_flow_models import SingleArticleReceipt
from .traffic_stats_aggregator import NetworkTrafficDelta, TrafficStatsAggregator


class MainFlowState:
    """主流程线程安全状态；不负责窗口、代理或数据库操作。"""

    def __init__(
        self,
        *,
        task_id: str,
        target_count: int,
        now: Callable[[], datetime] = datetime.now,
        traffic: TrafficStatsAggregator | None = None,
    ) -> None:
        self.task_id = task_id
        self.target_count = max(0, int(target_count))
        self._now = now
        self._lock = RLock()
        self._status = "idle"
        self._message = ""
        self._current_action = "点击开始运行后，将从桌面主页窗口读取"
        self._account_name = "等待识别"
        self._task_info = "待获取"
        self._progress_done = 0
        self._skipped_count = 0
        self._error_count = 0
        self._latest_error = ""
        self._active_worker_count = 0
        self._total_worker_count = 0
        self._average_total_seconds = 0.0
        self._average_count = 0
        self._handled_fingerprints: set[str] = set()
        self._traffic = traffic or TrafficStatsAggregator(now=now)

    def start(self) -> None:
        with self._lock:
            self._status = "running"
            self._current_action = "正在准备主流程"
            self._message = "主流程已启动"

    def set_starting(self) -> None:
        with self._lock:
            self._status = "starting"
            self._current_action = "正在准备主流程"
            self._message = "主流程正在启动"

    def request_stop(self) -> None:
        with self._lock:
            if self._status in {"running", "starting"}:
                self._status = "stopping"
                self._current_action = "正在清理运行资源"
                self._message = "已请求停止主流程"

    def complete(self, message: str = "主流程已完成") -> None:
        with self._lock:
            self._status = "completed"
            self._current_action = "主流程已完成"
            self._message = message
            self._traffic.reset()

    def fail(self, message: str) -> None:
        with self._lock:
            self._status = "failed"
            self._current_action = "主流程异常"
            self._message = message
            self._latest_error = message
            self._error_count += 1
            self._traffic.reset()

    def cancel(self, message: str = "主流程已停止") -> None:
        with self._lock:
            self._status = "cancelled"
            self._current_action = "主流程已停止"
            self._message = message
            self._traffic.reset()

    def set_action(self, action: str) -> None:
        value = str(action or "").strip()
        if value and not value.startswith("正在") and not value.startswith("主流程"):
            value = f"正在{value}"
        with self._lock:
            self._current_action = value

    def set_account_name(self, account_name: str) -> None:
        with self._lock:
            self._account_name = str(account_name or "").strip() or "等待识别"

    def set_task_info(self, task_info: str) -> None:
        with self._lock:
            self._task_info = str(task_info or "").strip() or "待获取"

    def begin_child_process(self, article_task_id: str | None = None) -> None:
        del article_task_id
        with self._lock:
            self._active_worker_count += 1
            self._total_worker_count += 1

    def end_child_process(self, article_task_id: str | None = None) -> None:
        del article_task_id
        with self._lock:
            self._active_worker_count = max(0, self._active_worker_count - 1)

    def append_traffic(self, delta: NetworkTrafficDelta) -> None:
        try:
            self._traffic.append(delta)
        except Exception:
            # 流量统计是辅助状态，坏事件不能影响采集主线。
            return

    def handle_receipt(self, receipt: SingleArticleReceipt) -> bool:
        """处理一次单篇回执；返回是否首次处理该 fingerprint。"""
        with self._lock:
            fingerprint = str(receipt.target_fingerprint or "")
            if fingerprint and fingerprint in self._handled_fingerprints:
                return False
            if fingerprint:
                self._handled_fingerprints.add(fingerprint)
            if receipt.status == "success" and receipt.article_saved:
                self._progress_done += 1
                duration = max(0.0, float(receipt.duration_seconds))
                self._average_total_seconds += duration
                self._average_count += 1
            elif receipt.status == "skipped_collected":
                self._skipped_count += 1
            elif receipt.status == "failed":
                self._error_count += 1
                self._latest_error = receipt.error_detail or receipt.message or "单篇任务失败"
            elif receipt.status == "cancelled":
                self._status = "stopping"
            return True

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            average = (
                self._average_total_seconds / self._average_count
                if self._average_count
                else None
            )
            total_label = "全部" if self.target_count == 0 else str(self.target_count)
            percent = (
                min(100, round(self._progress_done / self.target_count * 100))
                if self.target_count
                else 0
            )
            return {
                "status": self._status,
                "message": self._message,
                "currentAction": self._current_action,
                "accountName": self._account_name,
                "taskInfo": self._task_info,
                "proxyStatusLabel": "空闲",
                "progressDone": self._progress_done,
                "progressTotalLabel": total_label,
                "progressPercent": percent,
                "averageArticleSeconds": average,
                "averageArticleDurationLabel": "待统计" if average is None else f"{average:.1f} 秒",
                "activeWorkerCount": self._active_worker_count,
                "totalWorkerCount": self._total_worker_count,
                "errorCount": self._error_count,
                "latestError": self._latest_error,
                "skippedCount": self._skipped_count,
                "handledFingerprints": sorted(self._handled_fingerprints),
                "traffic": self._traffic.snapshot(),
                "updatedAt": self._now().isoformat(timespec="milliseconds"),
            }
