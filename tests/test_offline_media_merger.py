from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.modules.archive.offline_media_merger import (
    concat_local_media_segments,
    mux_local_media_streams,
)


class _SuccessfulRunner:
    def __init__(self) -> None:
        self.command: list[str] = []
        self.concat_list = ""

    def __call__(self, command, **_kwargs):
        self.command = list(command)
        if "concat" in self.command:
            list_path = Path(self.command[self.command.index("-i") + 1])
            self.concat_list = list_path.read_text(encoding="utf-8")
        Path(self.command[-1]).write_bytes(b"merged-media")
        return SimpleNamespace(returncode=0, stderr="")


class OfflineMediaMergerTest(unittest.TestCase):
    def test_concat_uses_local_concat_list_and_stream_copy(self) -> None:
        runner = _SuccessfulRunner()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "part-1.mp4"
            second = root / "part-2.mp4"
            output = root / "complete.mp4"
            first.write_bytes(b"first")
            second.write_bytes(b"second")

            result = concat_local_media_segments(
                [first, second],
                output,
                runner=runner,
                ffmpeg_exe_getter=lambda: "ffmpeg-test",
            )

            self.assertTrue(result.ok, result.message)
            self.assertEqual(output.read_bytes(), b"merged-media")
            self.assertEqual(runner.command[0], "ffmpeg-test")
            self.assertIn("-f", runner.command)
            self.assertIn("concat", runner.command)
            self.assertIn("copy", runner.command)
            self.assertIn(first.resolve().as_posix(), runner.concat_list)
            self.assertIn(second.resolve().as_posix(), runner.concat_list)

    def test_mux_uses_two_local_inputs_without_reencoding(self) -> None:
        runner = _SuccessfulRunner()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "video.mp4"
            audio = root / "audio.m4a"
            output = root / "complete.mp4"
            video.write_bytes(b"video")
            audio.write_bytes(b"audio")

            result = mux_local_media_streams(
                video,
                audio,
                output,
                runner=runner,
                ffmpeg_exe_getter=lambda: "ffmpeg-test",
            )

            self.assertTrue(result.ok, result.message)
            self.assertEqual(output.read_bytes(), b"merged-media")
            self.assertEqual(runner.command.count("-i"), 2)
            self.assertIn(str(video.resolve()), runner.command)
            self.assertIn(str(audio.resolve()), runner.command)
            self.assertIn("copy", runner.command)
            self.assertNotIn("http", " ".join(runner.command).lower())

    def test_failed_ffmpeg_does_not_replace_existing_output(self) -> None:
        def failed_runner(_command, **_kwargs):
            return SimpleNamespace(returncode=1, stderr="invalid media")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "part.mp4"
            output = root / "complete.mp4"
            first.write_bytes(b"part")
            output.write_bytes(b"existing")

            result = concat_local_media_segments(
                [first],
                output,
                runner=failed_runner,
                ffmpeg_exe_getter=lambda: "ffmpeg-test",
            )

            self.assertFalse(result.ok)
            self.assertIn("invalid media", result.message)
            self.assertEqual(output.read_bytes(), b"existing")


if __name__ == "__main__":
    unittest.main()
