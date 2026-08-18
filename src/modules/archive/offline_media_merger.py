from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Callable, Sequence
from uuid import uuid4

import imageio_ffmpeg


Runner = Callable[..., object]
FfmpegExeGetter = Callable[[], str]


@dataclass(frozen=True, slots=True)
class MediaMergeResult:
    ok: bool
    output_path: Path
    message: str = ""


def concat_local_media_segments(
    segment_paths: Sequence[str | Path],
    output_path: str | Path,
    *,
    runner: Runner = subprocess.run,
    ffmpeg_exe_getter: FfmpegExeGetter = imageio_ffmpeg.get_ffmpeg_exe,
) -> MediaMergeResult:
    """使用 FFmpeg concat demuxer 无损合并本地同类型媒体片段。"""
    output = Path(output_path)
    segments = tuple(Path(path).resolve() for path in segment_paths)
    invalid = _validate_local_inputs(segments)
    if invalid:
        return MediaMergeResult(False, output, invalid)

    output.parent.mkdir(parents=True, exist_ok=True)
    token = uuid4().hex
    list_path = output.parent / f".{output.stem}.{token}.concat.txt"
    temp_output = _temporary_output_path(output, token)
    try:
        list_path.write_text(
            "".join(f"file '{_escape_concat_path(path)}'\n" for path in segments),
            encoding="utf-8",
        )
        command = [
            ffmpeg_exe_getter(),
            "-y",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c",
            "copy",
            str(temp_output),
        ]
        return _run_and_commit(command, output, temp_output, runner=runner)
    except Exception as exc:
        return MediaMergeResult(
            False,
            output,
            f"本地媒体片段合并失败：{type(exc).__name__}: {exc}",
        )
    finally:
        list_path.unlink(missing_ok=True)
        temp_output.unlink(missing_ok=True)


def mux_local_media_streams(
    video_path: str | Path,
    audio_path: str | Path,
    output_path: str | Path,
    *,
    runner: Runner = subprocess.run,
    ffmpeg_exe_getter: FfmpegExeGetter = imageio_ffmpeg.get_ffmpeg_exe,
) -> MediaMergeResult:
    """使用 FFmpeg stream copy 合并本地独立视频轨和音频轨。"""
    output = Path(output_path)
    video = Path(video_path).resolve()
    audio = Path(audio_path).resolve()
    invalid = _validate_local_inputs((video, audio))
    if invalid:
        return MediaMergeResult(False, output, invalid)

    output.parent.mkdir(parents=True, exist_ok=True)
    temp_output = _temporary_output_path(output, uuid4().hex)
    try:
        command = [
            ffmpeg_exe_getter(),
            "-y",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-i",
            str(audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c",
            "copy",
            "-shortest",
            str(temp_output),
        ]
        return _run_and_commit(command, output, temp_output, runner=runner)
    except Exception as exc:
        return MediaMergeResult(
            False,
            output,
            f"本地音视频轨合并失败：{type(exc).__name__}: {exc}",
        )
    finally:
        temp_output.unlink(missing_ok=True)


def _run_and_commit(
    command: list[str],
    output_path: Path,
    temp_output: Path,
    *,
    runner: Runner,
) -> MediaMergeResult:
    completed = runner(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    return_code = int(getattr(completed, "returncode", 1) or 0)
    if return_code != 0:
        stderr = str(getattr(completed, "stderr", "") or "").strip()
        detail = stderr[-1000:] if stderr else f"FFmpeg 返回码 {return_code}"
        return MediaMergeResult(False, output_path, f"FFmpeg 合并失败：{detail}")
    if not temp_output.is_file() or temp_output.stat().st_size <= 0:
        return MediaMergeResult(False, output_path, "FFmpeg 未生成有效的本地媒体文件")
    os.replace(temp_output, output_path)
    return MediaMergeResult(True, output_path, "本地媒体合并完成")


def _validate_local_inputs(paths: Sequence[Path]) -> str:
    if not paths:
        return "没有可合并的本地媒体文件"
    for path in paths:
        if not path.is_file():
            return f"本地媒体文件不存在：{path.name}"
    return ""


def _temporary_output_path(output_path: Path, token: str) -> Path:
    suffix = output_path.suffix or ".media"
    return output_path.parent / f".{output_path.stem}.{token}.part{suffix}"


def _escape_concat_path(path: Path) -> str:
    return path.as_posix().replace("'", "'\\''")


__all__ = [
    "MediaMergeResult",
    "concat_local_media_segments",
    "mux_local_media_streams",
]
