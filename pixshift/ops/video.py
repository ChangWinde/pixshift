"""Orchestration wrappers for the video engine (atomic write + run)."""

from __future__ import annotations

import os
from collections.abc import Callable

from ..core.files import atomic_output_path
from ..video_engine import (
    FFMPEG_AVAILABLE,
    FFmpegNotAvailableError,
    VideoInfo,
    VideoOptimizeResult,
    VideoResult,
    analyze_video_info,
    build_compress_args,
    build_convert_args,
    build_extract_audio_args,
    build_gif_args,
    build_thumbnail_args,
    build_trim_args,
    probe,
    run_ffmpeg,
)


class _FfmpegError(RuntimeError):
    """A non-zero ffmpeg exit for one operation."""


def available() -> bool:
    """Whether ffmpeg/ffprobe are usable on this host."""
    return FFMPEG_AVAILABLE


def info(path: str) -> VideoInfo:
    """Probe one video file."""
    return probe(path)


def analyze_one(path: str) -> VideoOptimizeResult:
    """Probe one video and derive an optimize recommendation.

    ffmpeg being optional, its absence and probe failures become stable
    per-file errors so a mixed optimize batch can keep analysing images.
    """
    if not os.path.exists(path):
        return VideoOptimizeResult(input_path=path, error="input_not_found")
    size = os.path.getsize(path)
    if not FFMPEG_AVAILABLE:
        return VideoOptimizeResult(input_path=path, input_bytes=size, error="ffmpeg_missing")
    probed = probe(path)
    if probed.error:
        return VideoOptimizeResult(input_path=path, input_bytes=size, error=probed.error)
    return analyze_video_info(probed)


def _run_operation(
    src: str,
    dst: str,
    build: Callable[[str], list[str]],
    *,
    overwrite: bool,
) -> VideoResult:
    """Build args against a temp path, run ffmpeg, atomically publish on success."""
    result = VideoResult(input_path=src, output_path=dst)
    if not os.path.exists(src):
        result.error = "input_not_found"
        return result
    result.input_bytes = os.path.getsize(src)
    if os.path.exists(dst) and not overwrite:
        result.error = "output_exists"
        return result
    try:
        with atomic_output_path(dst) as temporary:
            returncode, tail = run_ffmpeg(build(temporary))
            if returncode != 0:
                # Raise so atomic_output_path discards the temp instead of
                # publishing a half-written file.
                raise _FfmpegError(tail)
    except FFmpegNotAvailableError:
        result.error = "ffmpeg_missing"
        return result
    except _FfmpegError as error:
        result.error = "ffmpeg_failed"
        result.detail = str(error)
        return result
    except ValueError as error:
        result.error = str(error)
        return result
    except OSError as error:
        # ffmpeg can exit 0 without producing its planned output (a failure
        # mode ADR-0005 calls out); atomic_output_path surfaces that as an
        # OSError which must stay a stable per-file error, not a traceback.
        result.error = "output_not_created"
        result.detail = str(error)
        return result
    result.output_bytes = os.path.getsize(dst)
    result.success = True
    return result


def convert_one(
    src: str,
    dst: str,
    *,
    container: str,
    codec: str | None = None,
    hwaccel: str | None = None,
    overwrite: bool = False,
) -> VideoResult:
    return _run_operation(
        src,
        dst,
        lambda tmp: build_convert_args(src, tmp, container=container, codec=codec, hwaccel=hwaccel),
        overwrite=overwrite,
    )


def compress_one(
    src: str,
    dst: str,
    *,
    preset: str,
    codec: str,
    crf: int | None = None,
    hwaccel: str | None = None,
    overwrite: bool = False,
) -> VideoResult:
    return _run_operation(
        src,
        dst,
        lambda tmp: build_compress_args(
            src, tmp, preset=preset, codec=codec, crf=crf, hwaccel=hwaccel
        ),
        overwrite=overwrite,
    )


def trim_one(
    src: str,
    dst: str,
    *,
    start: float,
    end: float | None = None,
    duration: float | None = None,
    reencode: bool = False,
    overwrite: bool = False,
) -> VideoResult:
    return _run_operation(
        src,
        dst,
        lambda tmp: build_trim_args(
            src, tmp, start=start, end=end, duration=duration, reencode=reencode
        ),
        overwrite=overwrite,
    )


def thumbnail_one(src: str, dst: str, *, at_seconds: float, overwrite: bool = False) -> VideoResult:
    return _run_operation(
        src,
        dst,
        lambda tmp: build_thumbnail_args(src, tmp, at_seconds=at_seconds),
        overwrite=overwrite,
    )


def extract_audio_one(
    src: str, dst: str, *, audio_ext: str, overwrite: bool = False
) -> VideoResult:
    return _run_operation(
        src,
        dst,
        lambda tmp: build_extract_audio_args(src, tmp, audio_ext=audio_ext),
        overwrite=overwrite,
    )


def gif_one(
    src: str,
    dst: str,
    *,
    start: float = 0.0,
    duration: float | None = None,
    fps: int = 12,
    width: int = 480,
    overwrite: bool = False,
) -> VideoResult:
    return _run_operation(
        src,
        dst,
        lambda tmp: build_gif_args(src, tmp, start=start, duration=duration, fps=fps, width=width),
        overwrite=overwrite,
    )
