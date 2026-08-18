from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.modules.archive.offline_media_downloader import (
    MediaCandidate,
    download_media_candidate,
)


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int,
        body: bytes,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body

    def iter_content(self, chunk_size: int):
        for offset in range(0, len(self._body), max(1, chunk_size)):
            yield self._body[offset : offset + chunk_size]

    def close(self) -> None:
        return None


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.cookies: dict[str, str] = {}
        self.requests: list[dict[str, object]] = []

    def get(self, url: str, **kwargs):
        self.requests.append({"url": url, **kwargs})
        return self._responses.pop(0)

    def close(self) -> None:
        return None


class _FailingSession:
    def __init__(self) -> None:
        self.cookies: dict[str, str] = {}

    def get(self, url: str, **_kwargs):
        raise RuntimeError(f"request failed for {url}")

    def close(self) -> None:
        return None


class OfflineMediaDownloaderTest(unittest.TestCase):
    def test_downloads_normal_200_response_to_media_assets(self) -> None:
        session = _FakeSession(
            [
                _FakeResponse(
                    status_code=200,
                    body=b"complete-video",
                    headers={"content-type": "video/mp4", "content-length": "14"},
                )
            ]
        )
        candidate = MediaCandidate(
            url="https://mpvideo.qpic.cn/article.f10002.mp4?auth_key=secret",
            content_type="video/mp4",
            request_headers={"referer": "https://mp.weixin.qq.com/s/example"},
        )

        with tempfile.TemporaryDirectory() as directory:
            result = download_media_candidate(
                candidate,
                Path(directory) / "assets",
                cookies=[{"name": "wxuin", "value": "123", "domain": ".qq.com"}],
                timeout_seconds=10.0,
                session_factory=lambda: session,
            )

            self.assertTrue(result.ok, result.message)
            self.assertEqual(result.local_path.read_bytes(), b"complete-video")
            self.assertEqual(result.relative_path.split("/")[:2], ["assets", "video"])
            self.assertFalse(result.local_path.with_suffix(result.local_path.suffix + ".part").exists())
            self.assertEqual(session.cookies["wxuin"], "123")
            self.assertNotIn("Range", session.requests[0]["headers"])

    def test_continues_forced_206_responses_until_content_range_is_complete(self) -> None:
        session = _FakeSession(
            [
                _FakeResponse(
                    status_code=206,
                    body=b"0123",
                    headers={"content-type": "video/mp4", "content-range": "bytes 0-3/10"},
                ),
                _FakeResponse(
                    status_code=206,
                    body=b"4567",
                    headers={"content-type": "video/mp4", "content-range": "bytes 4-7/10"},
                ),
                _FakeResponse(
                    status_code=206,
                    body=b"89",
                    headers={"content-type": "video/mp4", "content-range": "bytes 8-9/10"},
                ),
            ]
        )
        candidate = MediaCandidate(
            url="https://mpvideo.qpic.cn/article.f10002.mp4?auth_key=secret",
            content_type="video/mp4",
            request_headers={"user-agent": "Wechat Chromium", "range": "bytes=0-3"},
        )

        with tempfile.TemporaryDirectory() as directory:
            result = download_media_candidate(
                candidate,
                Path(directory) / "assets",
                cookies=[],
                timeout_seconds=10.0,
                session_factory=lambda: session,
            )

            self.assertTrue(result.ok, result.message)
            self.assertEqual(result.local_path.read_bytes(), b"0123456789")
            self.assertEqual(len(session.requests), 3)
            self.assertNotIn("Range", session.requests[0]["headers"])
            self.assertEqual(session.requests[1]["headers"]["Range"], "bytes=4-")
            self.assertEqual(session.requests[2]["headers"]["Range"], "bytes=8-")

    def test_rejects_m3u8_without_creating_a_fake_complete_video(self) -> None:
        session = _FakeSession([])
        candidate = MediaCandidate(
            url="https://example.com/live/index.m3u8?token=secret",
            content_type="application/vnd.apple.mpegurl",
            request_headers={},
        )

        with tempfile.TemporaryDirectory() as directory:
            result = download_media_candidate(
                candidate,
                Path(directory) / "assets",
                cookies=[],
                timeout_seconds=10.0,
                session_factory=lambda: session,
            )

            self.assertFalse(result.ok)
            self.assertIn("m3u8", result.message.lower())
            self.assertIsNone(result.local_path)
            self.assertEqual(session.requests, [])

    def test_network_failure_message_does_not_expose_authenticated_url(self) -> None:
        candidate = MediaCandidate(
            url="https://mpvideo.qpic.cn/video.mp4?auth_key=top-secret",
            content_type="video/mp4",
            request_headers={},
        )

        with tempfile.TemporaryDirectory() as directory:
            result = download_media_candidate(
                candidate,
                Path(directory) / "assets",
                cookies=[],
                timeout_seconds=10.0,
                session_factory=_FailingSession,
            )

            self.assertFalse(result.ok)
            self.assertIn("RuntimeError", result.message)
            self.assertNotIn("auth_key", result.message)
            self.assertNotIn("top-secret", result.message)


if __name__ == "__main__":
    unittest.main()
