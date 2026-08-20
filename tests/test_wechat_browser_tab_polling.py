from __future__ import annotations

import unittest

from src.modules.window.wechat_browser_tabs import (
    ArticleTabNotFoundError,
    WechatBrowserTabService,
)


class _EmptyTabAdapter:
    def list_tabs(self) -> list[object]:
        return []

    def close_tab(self, selected: object, *, home_window_handle: int) -> None:
        return None


class WechatBrowserTabPollingTests(unittest.TestCase):
    def test_opened_article_polling_uses_initial_interval_and_caps_at_max(self) -> None:
        now = 0.0
        sleeps: list[float] = []

        def monotonic() -> float:
            return now

        def sleep(seconds: float) -> None:
            nonlocal now
            sleeps.append(round(seconds, 3))
            now += seconds

        service = WechatBrowserTabService(
            adapter=_EmptyTabAdapter(),
            monotonic=monotonic,
            sleep=sleep,
        )

        with self.assertRaises(ArticleTabNotFoundError):
            service.wait_for_opened_article_tab(
                baseline={},
                timeout_seconds=0.5,
                poll_initial_interval_seconds=0.1,
                poll_max_interval_seconds=0.2,
                stable_delay_seconds=0,
            )

        self.assertGreaterEqual(len(sleeps), 3)
        self.assertEqual(sleeps[0], 0.1)
        self.assertLessEqual(max(sleeps), 0.2)


if __name__ == "__main__":
    unittest.main()
