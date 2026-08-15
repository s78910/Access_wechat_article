from __future__ import annotations

from types import SimpleNamespace
import unittest

from pydantic import ValidationError

from dev_server import WindowDiagnosticPayload
from src.services.runtime.window_diagnostic_service import WindowDiagnosticService


class _FakeCursor:
    def __init__(self) -> None:
        self.diagnostics: dict[str, int] = {}
        self.sent_steps: list[int] = []

    def refresh_visible(self, _home_window: object) -> list[object]:
        return []

    def _send_scroll(
        self,
        _home_window: object,
        *,
        direction: str,
        wheel_steps: int,
    ) -> bool:
        if direction != "down":
            raise AssertionError(f"非预期滚动方向：{direction}")
        self.sent_steps.append(wheel_steps)
        return True

    def _wait(self, _seconds: float) -> None:
        return None


class _ScrollDiagnosticService(WindowDiagnosticService):
    def __init__(self, *, cursor: _FakeCursor) -> None:
        config = SimpleNamespace(
            window=SimpleNamespace(
                scroll_initial_delay_seconds=0.0,
                scroll_probe_interval_seconds=0.1,
                lazy_load_timeout_seconds=3.0,
                activation_wait_seconds=0.05,
            )
        )
        super().__init__(
            config=config,
            window_factory=SimpleNamespace(),
            monotonic=lambda: 1.0,
        )
        self._cursor = cursor

    def _home_context(
        self,
        *,
        required: bool = True,
        activate: bool = False,
    ) -> tuple[object, object, object, float]:
        del required, activate
        return (
            object(),
            SimpleNamespace(handle=1),
            SimpleNamespace(account_name="测试公众号"),
            0.0,
        )

    def _create_cursor(self, reader: object, home_info: object) -> _FakeCursor:
        del reader, home_info
        return self._cursor


class WindowDiagnosticScrollStepsTests(unittest.TestCase):
    def test_payload_accepts_scroll_steps_up_to_two_hundred(self) -> None:
        payload = WindowDiagnosticPayload(action="scroll-page", scrollSteps=200)

        self.assertEqual(payload.scrollSteps, 200)

    def test_scroll_page_payload_requires_explicit_input_steps(self) -> None:
        with self.assertRaises(ValidationError):
            WindowDiagnosticPayload(action="scroll-page")

    def test_payload_rejects_scroll_steps_outside_supported_range(self) -> None:
        for value in (0, 201):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                WindowDiagnosticPayload(action="scroll-page", scrollSteps=value)

    def test_scroll_page_uses_request_steps_without_changing_yaml_default(self) -> None:
        cursor = _FakeCursor()
        service = _ScrollDiagnosticService(cursor=cursor)

        result = service.run("scroll-page", scroll_steps=73)

        self.assertTrue(result["ok"])
        self.assertEqual(cursor.sent_steps, [73])
        self.assertIn(
            {"label": "输入滚动步长", "value": "73"},
            result["items"],
        )
        settings_item = next(
            item for item in result["items"] if item["label"] == "对应设置"
        )
        self.assertIn("diagnostic_scroll_steps=73", settings_item["value"])
        self.assertNotIn("scroll_wheel_steps=", settings_item["value"])

    def test_scroll_page_service_rejects_missing_input_steps(self) -> None:
        service = _ScrollDiagnosticService(cursor=_FakeCursor())

        with self.assertRaisesRegex(ValueError, "必须提供滚动步长"):
            service.run("scroll-page")


if __name__ == "__main__":
    unittest.main()
