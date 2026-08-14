"""Orchestration wrappers for the video engine (atomic write + run)."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from ..core.errors import OperationPolicyError
from ..core.files import atomic_output_path, validate_aggregate_output_path
from ..video_engine import (
    COMPACT_AUDIO_BPS,
    COMPATIBLE_AUDIO_BPS,
    DEFAULT_AUDIO_POLICY,
    FFMPEG_AVAILABLE,
    MIN_TARGET_VIDEO_BPS,
    MIN_USABLE_DURATION_SEC,
    FFmpegNotAvailableError,
    VideoInfo,
    VideoOptimizeResult,
    VideoResult,
    analyze_video_info,
    build_bitrate_pass_args,
    build_compress_args,
    build_concat_args,
    build_concat_segment_args,
    build_convert_args,
    build_extract_audio_args,
    build_gif_args,
    build_thumbnail_args,
    build_trim_args,
    compute_target_video_bitrate,
    concat_list_content,
    probe,
    run_ffmpeg,
    validate_container_codec,
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
    audio_policy: str = "",
) -> VideoResult:
    """Build args against a temp path, run ffmpeg, atomically publish on success."""
    result = VideoResult(input_path=src, output_path=dst)
    result.audio_policy = audio_policy
    if audio_policy:
        result.audio_action = (
            "copy_if_present" if audio_policy == "preserve" else "transcode_if_present"
        )
    if not os.path.exists(src):
        result.error = "input_not_found"
        return result
    result.input_bytes = os.path.getsize(src)
    if os.path.exists(dst) and not overwrite:
        result.error = "output_exists"
        return result
    try:
        with atomic_output_path(dst, overwrite=overwrite) as temporary:
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
    except FileExistsError as error:
        result.error = "output_exists"
        result.detail = str(error)
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
    audio_policy: str = DEFAULT_AUDIO_POLICY,
) -> VideoResult:
    return _run_operation(
        src,
        dst,
        lambda tmp: build_convert_args(
            src,
            tmp,
            container=container,
            codec=codec,
            hwaccel=hwaccel,
            audio_policy=audio_policy,
        ),
        overwrite=overwrite,
        audio_policy=audio_policy,
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
    audio_policy: str = DEFAULT_AUDIO_POLICY,
) -> VideoResult:
    return _run_operation(
        src,
        dst,
        lambda tmp: build_compress_args(
            src,
            tmp,
            preset=preset,
            codec=codec,
            crf=crf,
            hwaccel=hwaccel,
            audio_policy=audio_policy,
        ),
        overwrite=overwrite,
        audio_policy=audio_policy,
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


def compress_to_target_one(
    src: str,
    dst: str,
    *,
    target_bytes: int,
    codec: str = "h264",
    hwaccel: str | None = None,
    overwrite: bool = False,
    audio_policy: str = DEFAULT_AUDIO_POLICY,
) -> VideoResult:
    """Encode ``src`` to fit under ``target_bytes`` at the best quality.

    Two-pass bitrate encoding for the software h264/h265/vp9 paths (the
    quality-optimal answer for a size budget); single-pass ABR for av1 and
    hardware encoders, which have no portable two-pass. One bounded retry
    with a scaled-down bitrate absorbs rate-control overshoot; a second miss
    is an honest ``target_size_missed`` with no output left behind.
    """
    result = VideoResult(input_path=src, output_path=dst)
    result.audio_policy = audio_policy
    result.audio_action = (
        "copy_if_present" if audio_policy == "preserve" else "transcode_if_present"
    )
    if audio_policy not in {"preserve", "compatible", "compact"}:
        result.error = f"unsupported_audio_policy:{audio_policy}"
        return result
    if not os.path.exists(src):
        result.error = "input_not_found"
        return result
    result.input_bytes = os.path.getsize(src)
    if os.path.exists(dst) and not overwrite:
        result.error = "output_exists"
        return result
    if target_bytes <= 0:
        result.error = "target_size_must_be_positive"
        return result

    if result.input_bytes <= target_bytes and Path(src).suffix.lower() == Path(dst).suffix.lower():
        # Already within budget: re-encoding could only lose quality.
        try:
            with atomic_output_path(dst, overwrite=overwrite) as temporary:
                shutil.copyfile(src, temporary)
        except FileExistsError as error:
            result.error = "output_exists"
            result.detail = str(error)
            return result
        except OSError as error:
            result.error = "output_not_created"
            result.detail = str(error)
            return result
        result.output_bytes = os.path.getsize(dst)
        result.success = True
        result.detail = "already_within_target"
        result.audio_action = "stream_copy"
        return result

    try:
        probed = probe(src)
    except FFmpegNotAvailableError:
        result.error = "ffmpeg_missing"
        return result
    if probed.error:
        result.error = probed.error
        return result
    if probed.duration_sec < MIN_USABLE_DURATION_SEC:
        result.error = "no_duration_signal"
        return result

    has_audio = bool(probed.audio_codec)
    audio_bps = (
        COMPATIBLE_AUDIO_BPS if audio_policy in {"preserve", "compatible"} else COMPACT_AUDIO_BPS
    )
    video_bps = compute_target_video_bitrate(
        target_bytes,
        probed.duration_sec,
        has_audio=has_audio,
        audio_bps=audio_bps,
    )
    if video_bps < MIN_TARGET_VIDEO_BPS:
        result.error = "target_size_too_small"
        result.detail = f"computed video bitrate {video_bps}bps"
        return result

    two_pass = hwaccel is None and codec != "av1"
    actual_size = 0
    for attempt in range(2):
        passlog_dir = tempfile.mkdtemp(prefix=".pixshift-passlog-")
        passlog = os.path.join(passlog_dir, "pass")
        try:
            if two_pass:
                returncode, tail = run_ffmpeg(
                    build_bitrate_pass_args(
                        src,
                        dst,
                        codec=codec,
                        video_bps=video_bps,
                        has_audio=has_audio,
                        pass_number=1,
                        passlog=passlog,
                        hwaccel=hwaccel,
                        audio_policy=audio_policy,
                    )
                )
                if returncode != 0:
                    result.error = "ffmpeg_failed"
                    result.detail = tail
                    return result
            try:
                with atomic_output_path(dst, overwrite=overwrite) as temporary:
                    returncode, tail = run_ffmpeg(
                        build_bitrate_pass_args(
                            src,
                            temporary,
                            codec=codec,
                            video_bps=video_bps,
                            has_audio=has_audio,
                            pass_number=2 if two_pass else None,
                            passlog=passlog,
                            hwaccel=hwaccel,
                            audio_policy=audio_policy,
                        )
                    )
                    if returncode != 0:
                        raise _FfmpegError(tail)
                    actual_size = os.path.getsize(temporary)
                    if actual_size > target_bytes:
                        raise _TargetMissed()
            except _FfmpegError as error:
                result.error = "ffmpeg_failed"
                result.detail = str(error)
                return result
            except _TargetMissed:
                if attempt == 0:
                    # Rate control overshot; scale the budget down and retry.
                    video_bps = max(
                        MIN_TARGET_VIDEO_BPS,
                        int(video_bps * target_bytes / actual_size * 0.95),
                    )
                    continue
                result.error = "target_size_missed"
                result.detail = f"encoded {actual_size} bytes for a {target_bytes} byte target"
                return result
            except FFmpegNotAvailableError:
                result.error = "ffmpeg_missing"
                return result
            except FileExistsError as error:
                result.error = "output_exists"
                result.detail = str(error)
                return result
            except OSError as error:
                result.error = "output_not_created"
                result.detail = str(error)
                return result
        finally:
            shutil.rmtree(passlog_dir, ignore_errors=True)
        break

    result.output_bytes = os.path.getsize(dst)
    result.detail = f"video_bitrate_{video_bps}"
    result.success = True
    return result


class _TargetMissed(RuntimeError):
    """The encoded candidate exceeded the byte budget."""


def concat_videos(
    paths: list[str],
    dst: str,
    *,
    reencode: bool = False,
    overwrite: bool = False,
) -> VideoResult:
    """Concatenate clips end to end (stream-copy unless ``reencode``)."""
    result = VideoResult(input_path=paths[0] if paths else "", output_path=dst)
    if len(paths) < 2:
        result.error = "concat_requires_two_inputs"
        return result
    try:
        validate_aggregate_output_path(paths, dst)
    except OperationPolicyError as error:
        result.error = error.code
        return result
    for path in paths:
        if not os.path.exists(path):
            result.error = "input_not_found"
            result.detail = path
            return result
    result.input_bytes = sum(os.path.getsize(path) for path in paths)
    if os.path.exists(dst) and not overwrite:
        result.error = "output_exists"
        return result
    if reencode:
        try:
            validate_container_codec(Path(dst).suffix, "h264")
        except ValueError as error:
            result.error = str(error)
            return result

    try:
        probes = [probe(path) for path in paths]
    except FFmpegNotAvailableError:
        result.error = "ffmpeg_missing"
        return result
    for probed in probes:
        if probed.error:
            result.error = probed.error
            result.detail = probed.path
            return result
    if not reencode:
        signatures = {
            (
                item.video_codec,
                item.video_profile,
                item.video_level,
                item.pixel_format,
                item.frame_rate,
                item.video_time_base,
                item.sample_aspect_ratio,
                item.field_order,
                item.video_extradata_hash,
                item.color_range,
                item.color_space,
                item.color_primaries,
                item.color_transfer,
                item.width,
                item.height,
                item.audio_codec,
                item.audio_sample_rate,
                item.audio_channels,
                item.audio_channel_layout,
                item.audio_sample_format,
                item.audio_time_base,
            )
            for item in probes
        }
        if len(signatures) > 1:
            result.error = "concat_requires_matching_streams"
            result.detail = "stream signatures differ; pass --reencode to normalise"
            return result

    list_dir = tempfile.mkdtemp(prefix=".pixshift-concat-")
    list_path = os.path.join(list_dir, "clips.txt")
    try:
        concat_paths = paths
        if reencode:
            # The concat demuxer itself cannot make heterogeneous inputs
            # compatible. Normalize each segment first, then stream-copy the
            # common signature into the requested final container.
            if any(item.width <= 0 or item.height <= 0 for item in probes):
                raise ValueError("concat_missing_dimensions")
            width = max(2, max(item.width for item in probes) // 2 * 2)
            height = max(2, max(item.height for item in probes) // 2 * 2)
            fps = max((item.fps for item in probes if item.fps > 0), default=30.0)
            include_audio = any(bool(item.audio_codec) for item in probes)
            concat_paths = []
            for index, (path, probed) in enumerate(zip(paths, probes, strict=True)):
                normalized = os.path.join(list_dir, f"segment-{index:04d}.mp4")
                returncode, tail = run_ffmpeg(
                    build_concat_segment_args(
                        path,
                        normalized,
                        width=width,
                        height=height,
                        fps=fps,
                        source_has_audio=bool(probed.audio_codec),
                        include_audio=include_audio,
                    )
                )
                if returncode != 0:
                    raise _FfmpegError(f"segment {index + 1}: {tail}")
                concat_paths.append(normalized)
        Path(list_path).write_text(concat_list_content(concat_paths), encoding="utf-8")
        with atomic_output_path(dst, overwrite=overwrite) as temporary:
            returncode, tail = run_ffmpeg(build_concat_args(list_path, temporary))
            if returncode != 0:
                raise _FfmpegError(tail)
    except _FfmpegError as error:
        result.error = "ffmpeg_failed"
        result.detail = str(error)
        return result
    except ValueError as error:
        result.error = str(error)
        return result
    except FileExistsError as error:
        result.error = "output_exists"
        result.detail = str(error)
        return result
    except OSError as error:
        result.error = "output_not_created"
        result.detail = str(error)
        return result
    finally:
        shutil.rmtree(list_dir, ignore_errors=True)

    result.output_bytes = os.path.getsize(dst)
    result.success = True
    return result


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
