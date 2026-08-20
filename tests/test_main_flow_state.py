from __future__ import annotations

import unittest

from src.services.main_flow.main_flow_models import SingleArticleReceipt
from src.services.main_flow.main_flow_state import MainFlowState


class MainFlowStateTests(unittest.TestCase):
    def test_skipped_receipt_does_not_consume_success_progress(self) -> None:
        state = MainFlowState(task_id="task-1", target_count=3)
        state.start()
        state.handle_receipt(
            SingleArticleReceipt(
                task_id="task-1",
                target_fingerprint="fp-skip",
                status="skipped_collected",
                foreground_done=True,
            )
        )

        snapshot = state.snapshot()

        self.assertEqual(snapshot["progressDone"], 0)
        self.assertEqual(snapshot["skippedCount"], 1)
        self.assertEqual(snapshot["errorCount"], 0)
        self.assertIn("fp-skip", snapshot["handledFingerprints"])

    def test_success_and_failure_update_counts_and_workers(self) -> None:
        state = MainFlowState(task_id="task-1", target_count=2)
        state.start()
        state.begin_child_process("article-1")
        state.handle_receipt(
            SingleArticleReceipt(
                task_id="task-1",
                target_fingerprint="fp-ok",
                status="success",
                foreground_done=True,
                article_saved=True,
                duration_seconds=2.5,
            )
        )
        state.end_child_process("article-1")
        state.handle_receipt(
            SingleArticleReceipt(
                task_id="task-1",
                target_fingerprint="fp-failed",
                status="failed",
                foreground_done=True,
                error_stage="html_save",
                error_detail="保存失败",
            )
        )

        snapshot = state.snapshot()

        self.assertEqual(snapshot["progressDone"], 1)
        self.assertEqual(snapshot["errorCount"], 1)
        self.assertEqual(snapshot["activeWorkerCount"], 0)
        self.assertEqual(snapshot["totalWorkerCount"], 1)
        self.assertEqual(snapshot["averageArticleSeconds"], 2.5)
        self.assertEqual(snapshot["averageArticleDurationLabel"], "2.5 秒")


if __name__ == "__main__":
    unittest.main()
