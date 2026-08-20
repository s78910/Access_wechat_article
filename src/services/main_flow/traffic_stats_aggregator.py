from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Literal


TrafficSource = Literal["mitm", "html_request", "comments", "offline_cache"]
TRAFFIC_SOURCES: tuple[TrafficSource, ...] = (
    "mitm",
    "html_request",
    "comments",
    "offline_cache",
)


@dataclass(frozen=True, slots=True)
class NetworkTrafficDelta:
    task_id: str
    article_task_id: str | None
    source: TrafficSource
    upload_bytes: int = 0
    download_bytes: int = 0
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        if self.source not in TRAFFIC_SOURCES:
            raise ValueError(f"不支持的流量来源：{self.source}")
        if int(self.upload_bytes) < 0 or int(self.download_bytes) < 0:
            raise ValueError("流量字节数不能为负数")


class TrafficStatsAggregator:
    """按最近窗口汇总程序内部上报的流量，不读取系统网卡。"""

    def __init__(
        self,
        *,
        window_seconds: float = 2.0,
        bucket_seconds: float = 0.1,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        if window_seconds <= 0 or bucket_seconds <= 0:
            raise ValueError("流量窗口和时间桶必须大于 0")
        self.window_seconds = float(window_seconds)
        self.bucket_seconds = float(bucket_seconds)
        self._now = now
        self._events: deque[NetworkTrafficDelta] = deque()

    def append(self, delta: NetworkTrafficDelta) -> None:
        self._prune(self._now())
        self._events.append(delta)

    def snapshot(self) -> dict[str, object]:
        now = self._now()
        self._prune(now)
        upload = sum(item.upload_bytes for item in self._events)
        download = sum(item.download_bytes for item in self._events)
        breakdown = {
            source: {"uploadBytes": 0, "downloadBytes": 0}
            for source in TRAFFIC_SOURCES
        }
        for item in self._events:
            values = breakdown[item.source]
            values["uploadBytes"] += item.upload_bytes
            values["downloadBytes"] += item.download_bytes
        upload_rate = int(round(upload / self.window_seconds))
        download_rate = int(round(download / self.window_seconds))
        return {
            "uploadRateBytesPerSecond": upload_rate,
            "downloadRateBytesPerSecond": download_rate,
            "uploadLabel": self._format_rate(upload_rate),
            "downloadLabel": self._format_rate(download_rate),
            "windowSeconds": self.window_seconds,
            "history": [],
            "updatedAt": now.isoformat(timespec="milliseconds"),
            "sourceBreakdown": breakdown,
        }

    def reset(self) -> None:
        self._events.clear()

    def _prune(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.window_seconds)
        while self._events and self._events[0].timestamp < cutoff:
            self._events.popleft()

    @staticmethod
    def _format_rate(value: int) -> str:
        if value <= 0:
            return "0 KB/s"
        kib = value / 1024
        if kib < 1024:
            return f"{kib:.1f} KB/s"
        return f"{kib / 1024:.1f} MB/s"
