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

    Runtime absence (for an incomplete/unsupported installation) and probe
    failures become stable per-file errors so a mixed optimize batch can keep
    analysing images.
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
    validation_error = _target_request_error(
        src,
        dst,
        target_bytes=target_bytes,
        audio_policy=audio_policy,
        overwrite=overwrite,
    )
    if validation_error:
        result.error = validation_error
        return result
    result.input_bytes = os.path.getsize(src)

    if result.input_bytes <= target_bytes and Path(src).suffix.lower() == Path(dst).suffix.lower():
        _copy_within_target(src, dst, result, overwrite=overwrite)
        return result

    probed = _probe_target_source(src, result)
    if probed is None:
        return result
    has_audio = bool(probed.audio_codec)
    video_bps = _target_video_bitrate(
        target_bytes, probed, has_audio=has_audio, audio_policy=audio_policy
    )
    if video_bps < MIN_TARGET_VIDEO_BPS:
        result.error = "target_size_too_small"
        result.detail = f"computed video bitrate {video_bps}bps"
        return result
    encoded_bps = _encode_target_with_retry(
        src,
        dst,
        target_bytes=target_bytes,
        video_bps=video_bps,
        codec=codec,
        hwaccel=hwaccel,
        has_audio=has_audio,
        audio_policy=audio_policy,
        overwrite=overwrite,
        result=result,
    )
    if encoded_bps is None:
        return result
    result.output_bytes = os.path.getsize(dst)
    result.detail = f"video_bitrate_{encoded_bps}"
    result.success = True
    return result


def _target_request_error(
    src: str,
    dst: str,
    *,
    target_bytes: int,
    audio_policy: str,
    overwrite: bool,
) -> str:
    if audio_policy not in {"preserve", "compatible", "compact"}:
        return f"unsupported_audio_policy:{audio_policy}"
    if not os.path.exists(src):
        return "input_not_found"
    if os.path.exists(dst) and not overwrite:
        return "output_exists"
    if target_bytes <= 0:
        return "target_size_must_be_positive"
    return ""


def _copy_within_target(src: str, dst: str, result: VideoResult, *, overwrite: bool) -> None:
    """Copy a fitting source without quality loss and map publication failures."""
    try:
        with atomic_output_path(dst, overwrite=overwrite) as temporary:
            shutil.copyfile(src, temporary)
    except FileExistsError as error:
        result.error = "output_exists"
        result.detail = str(error)
        return
    except OSError as error:
        result.error = "output_not_created"
        result.detail = str(error)
        return
    result.output_bytes = os.path.getsize(dst)
    result.success = True
    result.detail = "already_within_target"
    result.audio_action = "stream_copy"


def _probe_target_source(src: str, result: VideoResult) -> VideoInfo | None:
    try:
        probed = probe(src)
    except FFmpegNotAvailableError:
        result.error = "ffmpeg_missing"
        return None
    if probed.error:
        result.error = probed.error
        return None
    if probed.duration_sec < MIN_USABLE_DURATION_SEC:
        result.error = "no_duration_signal"
        return None
    return probed


def _target_video_bitrate(
    target_bytes: int,
    probed: VideoInfo,
    *,
    has_audio: bool,
    audio_policy: str,
) -> int:
    audio_bps = (
        COMPATIBLE_AUDIO_BPS if audio_policy in {"preserve", "compatible"} else COMPACT_AUDIO_BPS
    )
    return compute_target_video_bitrate(
        target_bytes,
        probed.duration_sec,
        has_audio=has_audio,
        audio_bps=audio_bps,
    )


def _encode_target_with_retry(
    src: str,
    dst: str,
    *,
    target_bytes: int,
    video_bps: int,
    codec: str,
    hwaccel: str | None,
    has_audio: bool,
    audio_policy: str,
    overwrite: bool,
    result: VideoResult,
) -> int | None:
    two_pass = hwaccel is None and codec != "av1"
    for attempt in range(2):
        try:
            actual_size = _encode_target_attempt(
                src,
                dst,
                target_bytes=target_bytes,
                video_bps=video_bps,
                codec=codec,
                hwaccel=hwaccel,
                has_audio=has_audio,
                audio_policy=audio_policy,
                overwrite=overwrite,
                two_pass=two_pass,
            )
        except _TargetMissed as error:
            actual_size = error.actual_size
            if attempt == 0:
                video_bps = max(
                    MIN_TARGET_VIDEO_BPS,
                    int(video_bps * target_bytes / actual_size * 0.95),
                )
                continue
            result.error = "target_size_missed"
            result.detail = f"encoded {actual_size} bytes for a {target_bytes} byte target"
            return None
        except Exception as error:
            _map_target_encode_error(result, error)
            return None
        return video_bps
    return None


def _encode_target_attempt(
    src: str,
    dst: str,
    *,
    target_bytes: int,
    video_bps: int,
    codec: str,
    hwaccel: str | None,
    has_audio: bool,
    audio_policy: str,
    overwrite: bool,
    two_pass: bool,
) -> int:
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
                raise _FfmpegError(tail)
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
                raise _TargetMissed(actual_size)
            return actual_size
    finally:
        shutil.rmtree(passlog_dir, ignore_errors=True)


def _map_target_encode_error(result: VideoResult, error: Exception) -> None:
    if isinstance(error, _FfmpegError):
        result.error = "ffmpeg_failed"
        result.detail = str(error)
    elif isinstance(error, FFmpegNotAvailableError):
        result.error = "ffmpeg_missing"
    elif isinstance(error, FileExistsError):
        result.error = "output_exists"
        result.detail = str(error)
    elif isinstance(error, OSError):
        result.error = "output_not_created"
        result.detail = str(error)
    else:
        raise error


class _TargetMissed(RuntimeError):
    """The encoded candidate exceeded the byte budget."""

    def __init__(self, actual_size: int) -> None:
        self.actual_size = actual_size
        super().__init__(str(actual_size))


def concat_videos(
    paths: list[str],
    dst: str,
    *,
    reencode: bool = False,
    overwrite: bool = False,
) -> VideoResult:
    """Concatenate clips end to end (stream-copy unless ``reencode``)."""
    result = VideoResult(input_path=paths[0] if paths else "", output_path=dst)
    try:
        _validate_concat_request(paths, dst, reencode=reencode, overwrite=overwrite)
    except Exception as error:
        _map_concat_error(result, error)
        return result
    result.input_bytes = sum(os.path.getsize(path) for path in paths)

    try:
        probes = [probe(path) for path in paths]
        _validate_concat_probes(probes, reencode=reencode)
        _run_concat(paths, probes, dst, reencode=reencode, overwrite=overwrite)
    except Exception as error:
        _map_concat_error(result, error)
        return result

    result.output_bytes = os.path.getsize(dst)
    result.success = True
    return result


def _validate_concat_request(
    paths: list[str], dst: str, *, reencode: bool, overwrite: bool
) -> None:
    if len(paths) < 2:
        raise ValueError("concat_requires_two_inputs")
    validate_aggregate_output_path(paths, dst)
    for path in paths:
        if not os.path.exists(path):
            raise _InputNotFoundError(path)
    if os.path.exists(dst) and not overwrite:
        raise _OutputExistsPreflight()
    if reencode:
        validate_container_codec(Path(dst).suffix, "h264")


def _validate_concat_probes(probes: list[VideoInfo], *, reencode: bool) -> None:
    for probed in probes:
        if probed.error:
            raise _ProbeError(probed.error, probed.path)
    if not reencode and len({_concat_signature(item) for item in probes}) > 1:
        raise _StreamMismatchError()


def _concat_signature(item: VideoInfo) -> tuple[object, ...]:
    """Return every stream field required for safe concat-demuxer copying."""
    return (
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


def _run_concat(
    paths: list[str],
    probes: list[VideoInfo],
    dst: str,
    *,
    reencode: bool,
    overwrite: bool,
) -> None:
    list_dir = tempfile.mkdtemp(prefix=".pixshift-concat-")
    try:
        concat_paths = _normalise_concat_paths(paths, probes, list_dir) if reencode else paths
        list_path = os.path.join(list_dir, "clips.txt")
        Path(list_path).write_text(concat_list_content(concat_paths), encoding="utf-8")
        with atomic_output_path(dst, overwrite=overwrite) as temporary:
            returncode, tail = run_ffmpeg(build_concat_args(list_path, temporary))
            if returncode != 0:
                raise _FfmpegError(tail)
    finally:
        shutil.rmtree(list_dir, ignore_errors=True)


def _normalise_concat_paths(paths: list[str], probes: list[VideoInfo], list_dir: str) -> list[str]:
    """Transcode heterogeneous inputs to one concat-demuxer-compatible signature."""
    if any(item.width <= 0 or item.height <= 0 for item in probes):
        raise ValueError("concat_missing_dimensions")
    width = max(2, max(item.width for item in probes) // 2 * 2)
    height = max(2, max(item.height for item in probes) // 2 * 2)
    fps = max((item.fps for item in probes if item.fps > 0), default=30.0)
    include_audio = any(bool(item.audio_codec) for item in probes)
    normalized_paths: list[str] = []
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
        normalized_paths.append(normalized)
    return normalized_paths


def _map_concat_error(result: VideoResult, error: Exception) -> None:
    if isinstance(error, OperationPolicyError):
        result.error = error.code
    elif isinstance(error, FFmpegNotAvailableError):
        result.error = "ffmpeg_missing"
    elif isinstance(error, _FfmpegError):
        result.error = "ffmpeg_failed"
        result.detail = str(error)
    elif isinstance(error, _ProbeError):
        result.error = error.code
        result.detail = error.path
    elif isinstance(error, _StreamMismatchError):
        result.error = "concat_requires_matching_streams"
        result.detail = "stream signatures differ; pass --reencode to normalise"
    elif isinstance(error, _InputNotFoundError):
        result.error = "input_not_found"
        result.detail = error.path
    elif isinstance(error, _OutputExistsPreflight):
        result.error = "output_exists"
    elif isinstance(error, FileExistsError):
        result.error = "output_exists"
        result.detail = str(error)
    elif isinstance(error, OSError):
        result.error = "output_not_created"
        result.detail = str(error)
    elif isinstance(error, ValueError):
        result.error = str(error)
    else:
        raise error


class _ProbeError(RuntimeError):
    def __init__(self, code: str, path: str) -> None:
        self.code = code
        self.path = path
        super().__init__(code)


class _StreamMismatchError(RuntimeError):
    """Stream-copy inputs do not share a complete ffprobe signature."""


class _InputNotFoundError(RuntimeError):
    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(path)


class _OutputExistsPreflight(RuntimeError):
    """The concat destination existed before encoding began."""


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
