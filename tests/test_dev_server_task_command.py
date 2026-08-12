from __future__ import annotations

from types import SimpleNamespace
import unittest

from dev_server import _task_command_from_payload


def _config(*, comment_default: bool = False, offline_default: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        comment=SimpleNamespace(enabled_by_default=comment_default),
        offline_cache=SimpleNamespace(enabled_by_default=offline_default),
        request=SimpleNamespace(request_interval_seconds=0.0),
    )


class TaskCommandFromPayloadTest(unittest.TestCase):
    def test_frontend_selections_are_passed_to_task_command(self) -> None:
        command = _task_command_from_payload(
            {
                "recordLimit": 2,
                "selections": {
                    "articleDetail": True,
                    "offlineArchive": True,
                    "commentInfo": True,
                    "skipCollectedRecords": False,
                },
            },
            _config(),
        )

        self.assertTrue(command.collect_comments)
        self.assertTrue(command.build_offline_cache)
        self.assertFalse(command.skip_collected_records)

    def test_frontend_selections_override_yaml_defaults(self) -> None:
        command = _task_command_from_payload(
            {
                "recordLimit": 1,
                "selections": {
                    "articleDetail": True,
                    "offlineArchive": False,
                    "commentInfo": False,
                    "skipCollectedRecords": True,
                },
            },
            _config(comment_default=True, offline_default=True),
        )

        self.assertFalse(command.collect_comments)
        self.assertFalse(command.build_offline_cache)
        self.assertTrue(command.skip_collected_records)

    def test_missing_frontend_selection_uses_yaml_defaults(self) -> None:
        command = _task_command_from_payload(
            {"recordLimit": 1},
            _config(comment_default=True, offline_default=True),
        )

        self.assertTrue(command.collect_comments)
        self.assertTrue(command.build_offline_cache)


if __name__ == "__main__":
    unittest.main()
