from __future__ import annotations

from pathlib import Path
import tempfile
import time
import unittest

from src.services.main_flow.main_flow_models import MainFlowCommand
from src.services.main_flow.main_flow_service import (
    MainFlowConflictError,
    MainFlowService,
)


class MainFlowServiceTests(unittest.TestCase):
    def test_start_runs_lifecycle_and_can_be_read_after_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = MainFlowService(
                project_root=temp_dir,
                config=object(),
                db_path=Path(temp_dir) / "data.sqlite3",
                storage_root=Path(temp_dir) / "storages",
                temp_root=Path(temp_dir) / "tmp",
                id_factory=lambda: "fixed",
            )

            initial = service.start(MainFlowCommand(target_count=1))
            finished = service.wait(initial.task_id, timeout_seconds=2)

        self.assertEqual(initial.status, "starting")
        self.assertEqual(finished.status, "completed")
        self.assertIn("主页扫描模块待接入", finished.message)
        self.assertIsNone(service.active_task_id)

    def test_running_service_rejects_second_start(self) -> None:
        release = False

        def runner(context, _command):
            while not release:
                time.sleep(0.005)
            context.state.complete("测试完成")

        with tempfile.TemporaryDirectory() as temp_dir:
            service = MainFlowService(
                project_root=temp_dir,
                config=object(),
                db_path=Path(temp_dir) / "data.sqlite3",
                storage_root=Path(temp_dir) / "storages",
                temp_root=Path(temp_dir) / "tmp",
                runner=runner,
            )
            first = service.start(MainFlowCommand())
            time.sleep(0.02)
            with self.assertRaises(MainFlowConflictError):
                service.start(MainFlowCommand())
            release = True
            service.wait(first.task_id, timeout_seconds=2)


if __name__ == "__main__":
    unittest.main()
