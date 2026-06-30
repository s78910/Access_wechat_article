from __future__ import annotations

import unittest

from src.core.process_manager import ManagedProcess, ProcessManager


class StubbornProcess:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.alive_checks = 0

    def is_alive(self) -> bool:
        self.alive_checks += 1
        return self.alive_checks <= 2

    def terminate(self) -> None:
        self.calls.append("terminate")

    def kill(self) -> None:
        self.calls.append("kill")

    def join(self, timeout: float = 0) -> None:
        self.calls.append(f"join:{timeout:g}")


class ProcessManagerTest(unittest.TestCase):
    def test_stop_worker_kills_process_when_terminate_does_not_exit(self) -> None:
        process = StubbornProcess()
        manager = ProcessManager(process_factory=lambda **_kwargs: process)
        manager._processes["article_capture"] = ManagedProcess(name="article_capture", process=process)

        stopped = manager.stop_worker("article_capture", timeout=1)

        self.assertTrue(stopped)
        self.assertEqual(process.calls, ["terminate", "join:1", "kill", "join:1"])


if __name__ == "__main__":
    unittest.main()
