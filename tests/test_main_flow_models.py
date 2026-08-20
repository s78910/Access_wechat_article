from __future__ import annotations

import unittest

from src.services.main_flow.main_flow_models import (
    HomeArticleTarget,
    MainFlowCommand,
    SingleArticleOptions,
    SingleArticleReceipt,
)


class MainFlowModelsTests(unittest.TestCase):
    def test_command_from_frontend_payload_preserves_date_and_selections(self) -> None:
        command = MainFlowCommand.from_payload(
            {
                "recordLimit": 0,
                "dateFilterMode": "range",
                "startDate": "2026-08-01",
                "endDate": "2026-08-20",
                "selections": {
                    "commentInfo": True,
                    "offlineArchive": True,
                    "offlineArchiveMode": "beta",
                    "skipCollectedRecords": True,
                },
            }
        )

        self.assertEqual(command.target_count, 0)
        self.assertEqual(command.date_filter_mode, "range")
        self.assertEqual(command.start_date, "2026-08-01")
        self.assertEqual(command.end_date, "2026-08-20")
        self.assertTrue(command.collect_comments)
        self.assertTrue(command.archive_offline)
        self.assertEqual(command.offline_archive_mode, "beta")
        self.assertTrue(command.skip_collected_records)

    def test_target_fingerprint_is_stable_without_coordinates(self) -> None:
        first = HomeArticleTarget(
            sequence=1,
            account_name="人民日报",
            article_date="2026-08-20",
            title_raw="标题原文",
            title_display="标题原文",
            card_rect=(0, 0, 500, 200),
            visible_rect=(0, 10, 500, 180),
            click_point=(250, 100),
        )
        second = HomeArticleTarget(
            sequence=99,
            account_name="人民日报",
            article_date="2026-08-20",
            title_raw="标题原文",
            title_display="标题原文",
            card_rect=(0, 500, 500, 200),
            visible_rect=(0, 500, 500, 180),
            click_point=(250, 590),
        )

        self.assertEqual(first.fingerprint, second.fingerprint)

    def test_receipt_round_trip_keeps_skip_status(self) -> None:
        receipt = SingleArticleReceipt(
            task_id="task-1",
            target_fingerprint="fp-1",
            status="skipped_collected",
            foreground_done=True,
            message="已采集，跳过",
        )

        restored = SingleArticleReceipt.from_dict(receipt.to_dict())

        self.assertEqual(restored.status, "skipped_collected")
        self.assertTrue(restored.foreground_done)
        self.assertFalse(restored.article_saved)
        self.assertEqual(SingleArticleOptions().collect_article_detail, True)


if __name__ == "__main__":
    unittest.main()
