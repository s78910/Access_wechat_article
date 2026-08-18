from __future__ import annotations

from contextlib import closing
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import time
import unittest

from src.services.task.window_click_flow_huey_service import (
    WindowClickFlowConflictError,
    WindowClickFlowHueyService,
)


_TERMINAL_STATUSES = {
    "completed",
    "failed",
    "stopped",
    "date-boundary",
    "date-not-found",
    "home-not-found",
}


class WindowClickFlowHueyServiceTests(unittest.TestCase):
    def test_executes_job_through_session_sqlite_queue(self) -> None:
        def runner(*, options, on_update, stop_requested, trace_store):
            self.assertEqual(options.max_records, 3)
            self.assertEqual(options.date_filter_mode, "all")
            self.assertFalse(stop_requested())
            on_update(
                {
                    "ok": False,
                    "status": "running",
                    "message": "正在读取主页",
                    "tone": "info",
                    "items": [],
                    "recognizedCount": 0,
                    "skippedCount": 0,
                    "stoppedByUser": False,
                }
            )
            trace_store.append_event(
                {
                    "event": "test-runner",
                    "message": "Huey worker已执行",
                }
            )
            return {
                "ok": True,
                "status": "completed",
                "message": "读取完成",
                "tone": "success",
                "items": [
                    {
                        "kind": "article",
                        "label": "第1条文章",
                        "value": "测试文章",
                    }
                ],
                "records": [{"title": "测试文章"}],
                "events": [],
                "recognizedCount": 1,
                "skippedCount": 0,
                "stoppedByUser": False,
            }

        with TemporaryDirectory() as temp_dir:
            service = WindowClickFlowHueyService(
                temp_root=Path(temp_dir),
                config=object(),
                window_factory=object(),
                runner=runner,
                session_id="session001",
                job_id_factory=lambda: "job001",
            )
            try:
                initial = service.start(max_records=3, date_filter_mode="all")
                final = _wait_for_terminal(service, initial["jobId"])

                self.assertEqual(initial["status"], "running")
                self.assertTrue(initial["hueyTaskId"])
                self.assertEqual(final["status"], "completed")
                self.assertEqual(final["recognizedCount"], 1)
                self.assertEqual(final["records"][0]["title"], "测试文章")
                self.assertTrue(Path(final["resultPath"]).is_file())

                queue_path = service.queue_database_path
                self.assertEqual(
                    queue_path,
                    Path(temp_dir).resolve()
                    / "huey"
                    / "window-click-flow-session001.sqlite3",
                )
                with closing(sqlite3.connect(queue_path)) as connection:
                    tables = {
                        row[0]
                        for row in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type = 'table'"
                        )
                    }
                self.assertTrue({"task", "schedule", "kv", "counter"} <= tables)
            finally:
                service.shutdown()

    def test_stop_request_is_observed_by_running_huey_task(self) -> None:
        runner_started = Event()

        def runner(*, options, on_update, stop_requested, trace_store):
            runner_started.set()
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and not stop_requested():
                time.sleep(0.01)
            return {
                "ok": True,
                "status": "stopped",
                "message": "已停止主页内容读取",
                "tone": "warning",
                "items": [],
                "records": [],
                "events": [],
                "recognizedCount": 0,
                "skippedCount": 0,
                "stoppedByUser": True,
            }

        with TemporaryDirectory() as temp_dir:
            service = WindowClickFlowHueyService(
                temp_root=Path(temp_dir),
                config=object(),
                window_factory=object(),
                runner=runner,
                session_id="session002",
                job_id_factory=lambda: "job002",
            )
            try:
                initial = service.start(max_records=1)
                self.assertTrue(runner_started.wait(2.0))

                stopping = service.stop(initial["jobId"])
                final = _wait_for_terminal(service, initial["jobId"])

                self.assertEqual(stopping["status"], "stop-requested")
                self.assertEqual(final["status"], "stopped")
                self.assertTrue(final["stoppedByUser"])
            finally:
                service.shutdown()

    def test_rejects_a_second_active_window_job(self) -> None:
        runner_started = Event()

        def runner(*, options, on_update, stop_requested, trace_store):
            runner_started.set()
            while not stop_requested():
                time.sleep(0.01)
            return {
                "ok": True,
                "status": "stopped",
                "message": "已停止",
                "tone": "warning",
                "items": [],
                "records": [],
                "events": [],
                "recognizedCount": 0,
                "skippedCount": 0,
                "stoppedByUser": True,
            }

        job_ids = iter(("job003", "job004"))
        with TemporaryDirectory() as temp_dir:
            service = WindowClickFlowHueyService(
                temp_root=Path(temp_dir),
                config=object(),
                window_factory=object(),
                runner=runner,
                session_id="session003",
                job_id_factory=lambda: next(job_ids),
            )
            try:
                first = service.start(max_records=1)
                self.assertTrue(runner_started.wait(2.0))
                self.assertTrue(service.is_active())

                with self.assertRaises(WindowClickFlowConflictError):
                    service.start(max_records=1)

                service.stop(first["jobId"])
                _wait_for_terminal(service, first["jobId"])
                self.assertFalse(service.is_active())
            finally:
                service.shutdown()


def _wait_for_terminal(
    service: WindowClickFlowHueyService,
    job_id: str,
    *,
    timeout_seconds: float = 3.0,
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        payload = service.get(job_id)
        if payload.get("status") in _TERMINAL_STATUSES:
            return payload
        time.sleep(0.01)
    raise AssertionError(f"Huey窗口诊断任务未在{timeout_seconds:g}秒内结束")


if __name__ == "__main__":
    unittest.main()
