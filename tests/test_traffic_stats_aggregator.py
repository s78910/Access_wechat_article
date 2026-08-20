from __future__ import annotations

from datetime import datetime, timedelta
import unittest

from src.services.main_flow.traffic_stats_aggregator import (
    NetworkTrafficDelta,
    TrafficStatsAggregator,
)


class TrafficStatsAggregatorTests(unittest.TestCase):
    def test_snapshot_uses_recent_two_second_window_and_source_breakdown(self) -> None:
        now = datetime(2026, 8, 20, 10, 0, 2)
        aggregator = TrafficStatsAggregator(now=lambda: now)
        aggregator.append(
            NetworkTrafficDelta(
                task_id="task-1",
                article_task_id="article-1",
                source="mitm",
                upload_bytes=100,
                download_bytes=900,
                timestamp=now - timedelta(seconds=1),
            )
        )
        aggregator.append(
            NetworkTrafficDelta(
                task_id="task-1",
                article_task_id="article-1",
                source="comments",
                upload_bytes=50,
                download_bytes=100,
                timestamp=now,
            )
        )

        snapshot = aggregator.snapshot()

        self.assertEqual(snapshot["uploadRateBytesPerSecond"], 75)
        self.assertEqual(snapshot["downloadRateBytesPerSecond"], 500)
        self.assertEqual(snapshot["sourceBreakdown"]["mitm"]["downloadBytes"], 900)
        self.assertEqual(snapshot["sourceBreakdown"]["comments"]["uploadBytes"], 50)

    def test_reset_clears_current_rate(self) -> None:
        aggregator = TrafficStatsAggregator()
        aggregator.append(
            NetworkTrafficDelta(
                task_id="task-1",
                article_task_id=None,
                source="html_request",
                upload_bytes=1,
                download_bytes=2,
            )
        )

        aggregator.reset()

        snapshot = aggregator.snapshot()
        self.assertEqual(snapshot["uploadRateBytesPerSecond"], 0)
        self.assertEqual(snapshot["downloadRateBytesPerSecond"], 0)
        self.assertEqual(snapshot["sourceBreakdown"]["html_request"]["downloadBytes"], 0)


if __name__ == "__main__":
    unittest.main()
