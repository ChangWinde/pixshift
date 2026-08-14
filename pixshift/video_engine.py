"""PixShift Video Engine — ffmpeg-backed video operations (optional pillar).

ffmpeg/ffprobe are treated like PyMuPDF: an optional system dependency probed
at runtime and reported by ``doctor``. The argv builders here are pure
functions (no I/O), so their correctness is unit-tested even on hosts without
ffmpeg installed; only ``probe``/``run_ffmpeg`` touch the binaries.

Security notes (see ADR-0005): every ffmpeg call uses an explicit argv list
(never a shell string), user paths are resolved to absolute form so a name
starting with ``-`` cannot be read as an option, filter strings only ever
interpolate validated numbers, and ffprobe/ffmpeg run with a timeout and
``-nostdin`` so a malformed container cannot hang the process.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import signal
import subprocess
import threading
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

PROBE_TIMEOUT_S = 20.0
DEFAULT_RUN_TIMEOUT_S = 3600.0

DEFAULT_VIDEO_CONTAINER = "mp4"
DEFAULT_VIDEO_PRESET = "web"
DEFAULT_VIDEO_CODEC = "h264"
DEFAULT_AUDIO_POLICY = "compatible"
DEFAULT_AUDIO_FORMAT = "mp3"
DEFAULT_THUMBNAIL_AT = "25%"
DEFAULT_GIF_FPS = 12
DEFAULT_GIF_WIDTH = 480

AUDIO_POLICIES = ("preserve", "compatible", "compact")
COMPATIBLE_AUDIO_BPS = 192_000
COMPACT_AUDIO_BPS = 96_000

VIDEO_INPUT_FORMATS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    ".avi",
    ".m4v",
    ".wmv",
    ".flv",
    ".mpg",
    ".mpeg",
    ".ts",
    ".3gp",
}

# codec key -> (ffmpeg encoder, default container extension, audio encoder)
VIDEO_CODECS: dict[str, tuple[str, str, str]] = {
    "h264": ("libx264", "mp4", "aac"),
    "h265": ("libx265", "mp4", "aac"),
    "vp9": ("libvpx-vp9", "webm", "libopus"),
    "av1": ("libsvtav1", "webm", "libopus"),
}

# container extension -> default codec key
CONTAINER_DEFAULT_CODEC: dict[str, str] = {
    "mp4": "h264",
    "mov": "h264",
    "mkv": "h265",
    "webm": "vp9",
}

CONTAINER_VIDEO_CODECS: dict[str, set[str]] = {
    "mp4": {"h264", "h265"},
    "mov": {"h264", "h265"},
    "mkv": set(VIDEO_CODECS),
    "webm": {"vp9", "av1"},
}

AUDIO_CODECS: dict[str, tuple[str, str]] = {
    # extension -> (ffmpeg encoder, default bitrate; "" means codec-native)
    "mp3": ("libmp3lame", "192k"),
    "aac": ("aac", "192k"),
    "m4a": ("aac", "192k"),
    "opus": ("libopus", "128k"),
    "flac": ("flac", ""),
    "wav": ("pcm_s16le", ""),
}

# preset -> {"description": str, codec: {crf/effort knobs}}
VIDEO_COMPRESS_PRESETS: dict[str, dict[str, Any]] = {
    "web": {
        "description": "Balanced size/quality for web and sharing.",
        "h264": {"crf": 23, "preset": "medium"},
        "h265": {"crf": 28, "preset": "medium"},
        "vp9": {"crf": 33},
        "av1": {"crf": 35, "preset": "8"},
    },
    "archive": {
        "description": "Near-visually-lossless, larger files.",
        "h264": {"crf": 18, "preset": "slow"},
        "h265": {"crf": 22, "preset": "slow"},
        "vp9": {"crf": 28},
        "av1": {"crf": 28, "preset": "6"},
    },
    "tiny": {
        "description": "Smallest size, caps the long edge at 1280px.",
        "h264": {"crf": 32, "preset": "fast"},
        "h265": {"crf": 35, "preset": "fast"},
        "vp9": {"crf": 45},
        "av1": {"crf": 45, "preset": "10"},
    },
}


class FFmpegNotAvailableError(RuntimeError):
    """ffmpeg/ffprobe are not installed on this host."""

    code = "ffmpeg_missing"


@dataclass
class VideoInfo:
    """Container/stream summary from ffprobe."""

    path: str
    exists: bool = True
    duration_sec: float = 0.0
    width: int = 0
    height: int = 0
    video_codec: str = ""
    video_profile: str = ""
    video_level: int = 0
    pixel_format: str = ""
    frame_rate: str = ""
    video_time_base: str = ""
    sample_aspect_ratio: str = ""
    field_order: str = ""
    video_extradata_hash: str = ""
    color_range: str = ""
    color_space: str = ""
    color_primaries: str = ""
    color_transfer: str = ""
    audio_codec: str = ""
    audio_sample_rate: int = 0
    audio_channels: int = 0
    audio_channel_layout: str = ""
    audio_sample_format: str = ""
    audio_time_base: str = ""
    fps: float = 0.0
    bit_rate: int = 0
    container: str = ""
    stream_count: int = 0
    size_bytes: int = 0
    error: str = ""


@dataclass
class VideoResult:
    """One video operation result."""

    input_path: str = ""
    output_path: str = ""
    success: bool = False
    input_bytes: int = 0
    output_bytes: int = 0
    duration_sec: float = 0.0
    error: str = ""
    detail: str = ""
    audio_policy: str = ""
    audio_action: str = ""


@dataclass
class VideoBatchResult:
    """Batch summary for multi-input video operations."""

    total: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    results: list[VideoResult] = field(default_factory=list)


def check_ffmpeg() -> None:
    """Raise a stable error when ffmpeg/ffprobe are missing."""
    if not FFMPEG_AVAILABLE:
        raise FFmpegNotAvailableError(
            "视频功能需要 ffmpeg。请安装: brew install ffmpeg / apt install ffmpeg"
        )


def parse_timecode(value: str) -> float:
    """Parse ``HH:MM:SS(.ms)`` / ``MM:SS`` / seconds into float seconds.

    Rejects negatives, empty strings, non-numeric parts, and more than three
    colon-separated fields so a caller cannot smuggle arbitrary text into an
    ffmpeg ``-ss``/``-to`` argument.
    """
    text = value.strip()
    if not text:
        raise ValueError("invalid_timecode")
    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError("invalid_timecode")
    try:
        numbers = [float(part) for part in parts]
    except ValueError as error:
        raise ValueError("invalid_timecode") from error
    # Reject negatives and non-finite values ("inf"/"nan" parse as floats but
    # would otherwise flow into ffmpeg arguments as literal inf/nan).
    if any(number < 0 or not math.isfinite(number) for number in numbers):
        raise ValueError("invalid_timecode")
    seconds = 0.0
    for number in numbers:
        seconds = seconds * 60.0 + number
    return seconds


def _safe_path(path: str) -> str:
    """Return an absolute path ffmpeg cannot mistake for an option."""
    resolved = os.fspath(Path(path).resolve())
    if resolved.startswith("-"):
        # Extremely unlikely for a resolved absolute path, but keep the invariant.
        raise ValueError("unsafe_path")
    return resolved


# ============================================================
#  Pure argv builders (no I/O; unit-tested without ffmpeg)
# ============================================================

# Opt-in hardware encode backends: (backend, codec key) -> ffmpeg encoder.
# VA-API is deliberately absent (device/filter-graph plumbing); vp9/av1
# hardware encoders are too niche to promise portable behaviour.
HWACCEL_BACKENDS = ("videotoolbox", "nvenc", "qsv")
_HW_ENCODERS: dict[tuple[str, str], str] = {
    ("nvenc", "h264"): "h264_nvenc",
    ("nvenc", "h265"): "hevc_nvenc",
    ("qsv", "h264"): "h264_qsv",
    ("qsv", "h265"): "hevc_qsv",
    ("videotoolbox", "h264"): "h264_videotoolbox",
    ("videotoolbox", "h265"): "hevc_videotoolbox",
}
# x264/x265-style speed presets translated onto NVENC's p1(fast)..p7(slow).
_NVENC_PRESETS = {"fast": "p4", "medium": "p5", "slow": "p6"}


def _hw_encoder(codec_key: str, hwaccel: str) -> str:
    encoder = _HW_ENCODERS.get((hwaccel, codec_key))
    if encoder is None:
        raise ValueError(f"unsupported_hwaccel:{hwaccel}:{codec_key}")
    return encoder


def _hw_quality_args(hwaccel: str, crf: int, preset: str | None) -> list[str]:
    """Translate a CRF-style quality target onto one backend's own knobs."""
    if hwaccel == "nvenc":
        args = ["-rc", "vbr", "-cq", str(crf)]
        if preset:
            args += ["-preset", _NVENC_PRESETS.get(preset, "p5")]
        return args
    if hwaccel == "qsv":
        args = ["-global_quality", str(crf)]
        if preset:
            args += ["-preset", preset]
        return args
    # videotoolbox: -q:v runs 1..100 with higher = better quality; map the
    # 0..51 CRF scale linearly and clamp. It has no speed presets.
    quality = max(1, min(100, round((51 - crf) * 2)))
    return ["-q:v", str(quality)]


def _video_encoder_args(
    codec_key: str, *, crf: int, speed_preset: str | None, hwaccel: str | None
) -> list[str]:
    """``-c:v`` and quality knobs for one encode, software or hardware."""
    if hwaccel is not None:
        args = ["-c:v", _hw_encoder(codec_key, hwaccel)]
        args += _hw_quality_args(hwaccel, crf, speed_preset)
    else:
        encoder = VIDEO_CODECS[codec_key][0]
        args = ["-c:v", encoder, "-crf", str(crf)]
        if codec_key in ("h264", "h265") and speed_preset:
            args += ["-preset", speed_preset]
        elif codec_key == "vp9":
            args += ["-b:v", "0"]
        elif codec_key == "av1" and speed_preset:
            args += ["-preset", speed_preset]
    if codec_key == "h265":
        args += ["-tag:v", "hvc1"]
    return args


def validate_container_codec(container: str, codec: str) -> None:
    """Reject container / video-codec pairs the CLI does not support."""
    normalized = container.lower().lstrip(".")
    if normalized not in CONTAINER_VIDEO_CODECS:
        raise ValueError(f"unsupported_target_container:{normalized}")
    if codec not in VIDEO_CODECS:
        raise ValueError(f"unsupported_video_codec:{codec}")
    if codec not in CONTAINER_VIDEO_CODECS[normalized]:
        raise ValueError(f"unsupported_codec_for_container:{codec}:{normalized}")


def _audio_args(codec: str, audio_policy: str) -> list[str]:
    """Return explicit audio handling for a video transcode."""
    if audio_policy not in AUDIO_POLICIES:
        raise ValueError(f"unsupported_audio_policy:{audio_policy}")
    if audio_policy == "preserve":
        return ["-c:a", "copy"]
    bitrate = COMPATIBLE_AUDIO_BPS if audio_policy == "compatible" else COMPACT_AUDIO_BPS
    return ["-c:a", VIDEO_CODECS[codec][2], "-b:a", str(bitrate)]


def build_convert_args(
    src: str,
    dst: str,
    *,
    container: str,
    codec: str | None = None,
    hwaccel: str | None = None,
    audio_policy: str = DEFAULT_AUDIO_POLICY,
) -> list[str]:
    """Argv to transcode ``src`` into ``container`` (default codec per container)."""
    container = container.lower().lstrip(".")
    if container not in CONTAINER_DEFAULT_CODEC:
        raise ValueError(f"unsupported_target_container:{container}")
    codec_key = codec or CONTAINER_DEFAULT_CODEC[container]
    validate_container_codec(container, codec_key)
    defaults: dict[str, tuple[int, str | None]] = {
        "h264": (23, "medium"),
        "h265": (23, "medium"),
        "vp9": (33, None),
        "av1": (35, "8"),
    }
    crf, speed_preset = defaults[codec_key]
    args = ["-i", _safe_path(src), "-map", "0:V:0", "-map", "0:a:0?", "-sn", "-dn"]
    args += _video_encoder_args(codec_key, crf=crf, speed_preset=speed_preset, hwaccel=hwaccel)
    args += _audio_args(codec_key, audio_policy)
    if container in ("mp4", "mov"):
        args += ["-movflags", "+faststart"]
    args.append(_safe_path(dst))
    return args


def build_compress_args(
    src: str,
    dst: str,
    *,
    preset: str,
    codec: str,
    crf: int | None = None,
    hwaccel: str | None = None,
    audio_policy: str = DEFAULT_AUDIO_POLICY,
) -> list[str]:
    """Argv to compress ``src`` using a preset/codec, optional CRF override."""
    if preset not in VIDEO_COMPRESS_PRESETS:
        raise ValueError(f"unsupported_video_preset:{preset}")
    if codec not in VIDEO_CODECS:
        raise ValueError(f"unsupported_video_codec:{codec}")
    knobs = VIDEO_COMPRESS_PRESETS[preset][codec]
    effective_crf = crf if crf is not None else int(knobs["crf"])
    speed_preset = str(knobs["preset"]) if "preset" in knobs else None
    args = ["-i", _safe_path(src), "-map", "0:V:0", "-map", "0:a:0?", "-sn", "-dn"]
    args += _video_encoder_args(
        codec, crf=effective_crf, speed_preset=speed_preset, hwaccel=hwaccel
    )
    if preset == "tiny":
        # Two aspect-preserving passes cap landscape width and portrait height;
        # -2 keeps the derived dimension even for the encoder.
        args += ["-vf", "scale='min(1280,iw)':-2,scale=-2:'min(1280,ih)'"]
    args += _audio_args(codec, audio_policy)
    container = VIDEO_CODECS[codec][1]
    if container in ("mp4", "mov"):
        args += ["-movflags", "+faststart"]
    args.append(_safe_path(dst))
    return args


def build_trim_args(
    src: str,
    dst: str,
    *,
    start: float,
    end: float | None = None,
    duration: float | None = None,
    reencode: bool = False,
) -> list[str]:
    """Argv to cut ``[start, end|start+duration)``; stream-copy unless reencode."""
    if end is not None and duration is not None:
        raise ValueError("trim_end_and_duration_are_mutually_exclusive")
    if end is not None and end <= start:
        raise ValueError("trim_end_must_exceed_start")
    if duration is not None and duration <= 0:
        raise ValueError("trim_duration_must_be_positive")
    args = [
        "-ss",
        f"{start:.3f}",
        "-i",
        _safe_path(src),
        "-map",
        "0:V:0",
        "-map",
        "0:a:0?",
        "-sn",
        "-dn",
    ]
    if end is not None:
        args += ["-t", f"{end - start:.3f}"]
    elif duration is not None:
        args += ["-t", f"{duration:.3f}"]
    if reencode:
        args += ["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-c:a", "aac"]
    else:
        args += ["-c", "copy"]
    args.append(_safe_path(dst))
    return args


def build_thumbnail_args(src: str, dst: str, *, at_seconds: float) -> list[str]:
    """Argv to grab a single still frame at ``at_seconds``."""
    if at_seconds < 0:
        raise ValueError("thumbnail_time_must_be_non_negative")
    return [
        "-ss",
        f"{at_seconds:.3f}",
        "-i",
        _safe_path(src),
        "-map",
        "0:V:0",
        "-an",
        "-sn",
        "-dn",
        "-frames:v",
        "1",
        _safe_path(dst),
    ]


def build_extract_audio_args(src: str, dst: str, *, audio_ext: str) -> list[str]:
    """Argv to export the audio track into ``audio_ext``."""
    audio_ext = audio_ext.lower().lstrip(".")
    if audio_ext not in AUDIO_CODECS:
        raise ValueError(f"unsupported_audio_format:{audio_ext}")
    encoder, bitrate = AUDIO_CODECS[audio_ext]
    args = [
        "-i",
        _safe_path(src),
        "-map",
        "0:a:0",
        "-vn",
        "-sn",
        "-dn",
        "-c:a",
        encoder,
    ]
    if bitrate:
        args += ["-b:a", bitrate]
    args.append(_safe_path(dst))
    return args


def build_gif_args(
    src: str,
    dst: str,
    *,
    start: float = 0.0,
    duration: float | None = None,
    fps: int = 12,
    width: int = 480,
) -> list[str]:
    """Argv to make an animated GIF via a one-pass palettegen/paletteuse graph."""
    if fps <= 0 or fps > 60:
        raise ValueError("gif_fps_out_of_range")
    if width <= 0 or width > 4096:
        raise ValueError("gif_width_out_of_range")
    if start < 0:
        raise ValueError("gif_start_must_be_non_negative")
    args = [
        "-ss",
        f"{start:.3f}",
        "-i",
        _safe_path(src),
        "-an",
        "-sn",
        "-dn",
    ]
    if duration is not None:
        if duration <= 0:
            raise ValueError("gif_duration_must_be_positive")
        args += ["-t", f"{duration:.3f}"]
    # Numbers are validated ints/floats above, never raw user strings.
    filtergraph = (
        f"[0:v:0]fps={fps},scale={width}:-1:flags=lanczos,split[a][b];"
        "[a]palettegen[p];[b][p]paletteuse[gif]"
    )
    args += ["-filter_complex", filtergraph, "-map", "[gif]", "-loop", "0", _safe_path(dst)]
    return args


# ============================================================
#  Target-size encoding and concatenation (pure; no I/O)
# ============================================================

# Reserve a slice of the byte budget for container/mux overhead.
TARGET_SIZE_OVERHEAD = 0.02
# Below this video bitrate the output is unusable; fail instead of encoding.
MIN_TARGET_VIDEO_BPS = 8_000
# Beyond any consumer codec's useful range; also keeps garbage probe
# durations from injecting astronomically long numbers into ffmpeg argv.
MAX_TARGET_VIDEO_BPS = 2_000_000_000
# Durations below this are probe garbage, not encodable clips.
MIN_USABLE_DURATION_SEC = 0.05
TARGET_AUDIO_BPS = COMPATIBLE_AUDIO_BPS


def compute_target_video_bitrate(
    target_bytes: int,
    duration_sec: float,
    *,
    has_audio: bool,
    audio_bps: int = TARGET_AUDIO_BPS,
) -> int:
    """Video bitrate (bps) that fits ``target_bytes`` over ``duration_sec``.

    Deterministic budget math: total bits over the duration, minus a fixed
    container-overhead reserve, minus the audio track's share, clamped into
    ``[0, MAX_TARGET_VIDEO_BPS]`` — the clamp keeps the function monotone in
    the budget even when a tiny duration explodes the division. The caller
    rejects values below ``MIN_TARGET_VIDEO_BPS``.
    """
    if target_bytes <= 0 or not math.isfinite(duration_sec):
        return 0
    if duration_sec < MIN_USABLE_DURATION_SEC:
        return 0
    total_bps = target_bytes * 8.0 / duration_sec
    video_bps = total_bps * (1.0 - TARGET_SIZE_OVERHEAD)
    if has_audio:
        video_bps -= audio_bps
    if not math.isfinite(video_bps) or video_bps <= 0:
        return 0
    return min(int(video_bps), MAX_TARGET_VIDEO_BPS)


def build_bitrate_pass_args(
    src: str,
    dst: str,
    *,
    codec: str,
    video_bps: int,
    has_audio: bool,
    pass_number: int | None,
    passlog: str,
    hwaccel: str | None = None,
    audio_policy: str = DEFAULT_AUDIO_POLICY,
) -> list[str]:
    """Argv for one bitrate-targeted encode pass.

    ``pass_number`` of 1/2 drives classic two-pass encoding (pass 1 analyses
    into ``passlog`` and writes to the null sink); ``None`` means single-pass
    ABR (used for av1 and hardware encoders, which have no portable two-pass).
    """
    if codec not in VIDEO_CODECS:
        raise ValueError(f"unsupported_video_codec:{codec}")
    if video_bps <= 0:
        raise ValueError("target_bitrate_must_be_positive")
    args = ["-i", _safe_path(src), "-map", "0:V:0", "-sn", "-dn"]
    if pass_number != 1 and has_audio:
        args += ["-map", "0:a:0"]
    if hwaccel is not None:
        args += ["-c:v", _hw_encoder(codec, hwaccel)]
        if hwaccel == "nvenc":
            args += ["-rc", "vbr"]
    else:
        args += ["-c:v", VIDEO_CODECS[codec][0]]
    args += ["-b:v", str(video_bps), "-maxrate", str(int(video_bps * 1.2))]
    args += ["-bufsize", str(int(video_bps * 2))]
    if codec == "h265":
        args += ["-tag:v", "hvc1"]
    if pass_number is not None:
        args += ["-pass", str(pass_number), "-passlogfile", passlog]
    if pass_number == 1:
        # Analysis pass: no audio, no container, discard the output.
        args += ["-an", "-f", "null", os.devnull]
        return args
    if has_audio:
        args += _audio_args(codec, audio_policy)
    else:
        args += ["-an"]
    container = VIDEO_CODECS[codec][1]
    if container in ("mp4", "mov"):
        args += ["-movflags", "+faststart"]
    args.append(_safe_path(dst))
    return args


def concat_list_content(paths: list[str]) -> str:
    """The ffmpeg concat-demuxer list document for ``paths``.

    Single quotes inside a path use the demuxer's ``'\\''`` escape; paths are
    absolutised so the list file's own location cannot change resolution.
    """
    lines = []
    for path in paths:
        resolved = _safe_path(path)
        if "\n" in resolved or "\r" in resolved:
            # The demuxer parses one entry per line and quotes do not span
            # lines, so a newline in a (legal on Linux) filename would inject
            # extra list entries. Reject it with a stable error instead.
            raise ValueError("unsupported_path_character")
        escaped = resolved.replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    return "\n".join(lines) + "\n"


def build_concat_args(list_path: str, dst: str, *, reencode: bool = False) -> list[str]:
    """Argv to concatenate the clips listed in ``list_path`` into ``dst``."""
    # "-safe 0" is required because the list holds absolute paths, but it also
    # lets the demuxer honour protocol prefixes in list entries. Restricting the
    # whitelist to "file" keeps a crafted entry from reaching the network.
    args = [
        "-f",
        "concat",
        "-safe",
        "0",
        "-protocol_whitelist",
        "file",
        "-i",
        _safe_path(list_path),
        "-map",
        "0:V:0",
        "-map",
        "0:a:0?",
        "-sn",
        "-dn",
    ]
    if reencode:
        validate_container_codec(Path(dst).suffix, "h264")
        args += ["-c:v", "libx264", "-crf", "23", "-preset", "medium", "-c:a", "aac"]
        args += ["-b:a", "128k"]
    else:
        args += ["-c", "copy"]
    if Path(dst).suffix.lower() in (".mp4", ".mov"):
        args += ["-movflags", "+faststart"]
    args.append(_safe_path(dst))
    return args


def build_concat_segment_args(
    src: str,
    dst: str,
    *,
    width: int,
    height: int,
    fps: float,
    source_has_audio: bool,
    include_audio: bool,
) -> list[str]:
    """Normalize one heterogeneous concat segment to a common MP4 signature."""
    if width <= 0 or height <= 0:
        raise ValueError("concat_missing_dimensions")
    if not math.isfinite(fps) or fps <= 0 or fps > 240:
        raise ValueError("concat_invalid_frame_rate")
    args = ["-i", _safe_path(src)]
    if include_audio and not source_has_audio:
        args += [
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
        ]
    args += ["-map", "0:V:0"]
    if include_audio:
        args += ["-map", "0:a:0" if source_has_audio else "1:a:0"]
    args += ["-sn", "-dn"]
    filtergraph = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps:.6f}"
    )
    args += [
        "-vf",
        filtergraph,
        "-c:v",
        "libx264",
        "-crf",
        "23",
        "-preset",
        "medium",
        "-pix_fmt",
        "yuv420p",
    ]
    if include_audio:
        # Pad a short real track (or the synthetic silent track) and let the
        # video stream determine segment duration. Bare ``-shortest`` would
        # truncate video whenever its original audio ended first.
        args += [
            "-af",
            "apad",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-shortest",
        ]
    else:
        args += ["-an"]
    args += ["-movflags", "+faststart", _safe_path(dst)]
    return args


# ============================================================
#  Probe-driven optimize analysis (pure; no I/O)
# ============================================================

# Source codecs a modern CRF encode roughly halves (or better).
LEGACY_VIDEO_CODECS = {
    "cinepak",
    "flv1",
    "h263",
    "indeo3",
    "indeo5",
    "mpeg1video",
    "mpeg2video",
    "mpeg4",
    "msmpeg4v1",
    "msmpeg4v2",
    "msmpeg4v3",
    "rv10",
    "rv20",
    "rv30",
    "rv40",
    "svq1",
    "svq3",
    "theora",
    "vc1",
    "vp6",
    "vp6f",
    "vp8",
    "wmv1",
    "wmv2",
    "wmv3",
}

# ffprobe codec_name -> our encoder key for same-family re-encodes.
_MODERN_CODEC_KEYS = {"h264": "h264", "hevc": "h265", "vp9": "vp9", "av1": "av1"}

# Above this many encoded bits per pixel per frame a re-encode pays off ...
WORTHWHILE_BPP = {"h264": 0.15, "h265": 0.11, "vp9": 0.11, "av1": 0.09}
# ... and this is roughly where a "web" CRF encode lands (size estimate).
TARGET_BPP = {"h264": 0.10, "h265": 0.07, "vp9": 0.07, "av1": 0.06}

# Anything this fat that is neither legacy nor modern is an editing
# intermediate (ProRes, DNxHD, MJPEG, raw): H.264 is the safe universal move.
INTERMEDIATE_BPP = 0.5

# Containers our convert path targets; other extensions get modernised to mp4.
MODERN_CONTAINER_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv"}

_AUDIO_ESTIMATE_BPS = 128_000.0


@dataclass
class VideoOptimizeResult:
    """Probe-driven optimize recommendation for one video."""

    input_path: str = ""
    input_bytes: int = 0
    duration_sec: float = 0.0
    width: int = 0
    height: int = 0
    video_codec: str = ""
    bits_per_pixel: float = 0.0
    action: str = ""  # video.convert / video.compress / keep
    recommended: str = ""
    reason: str = ""
    estimated_bytes: int = 0
    plan: dict[str, Any] = field(default_factory=dict)
    error: str = ""


def _pixel_rate(info: VideoInfo) -> float:
    """Pixels encoded per second, or 0 when the probe lacks a usable signal."""
    if info.width <= 0 or info.height <= 0 or info.fps <= 0:
        return 0.0
    if not math.isfinite(info.fps):
        return 0.0
    return float(info.width * info.height) * info.fps


def _estimate_video_bytes(info: VideoInfo, target_codec: str) -> int:
    """Deterministic size estimate for a re-encode at the target's web CRF."""
    pixel_rate = _pixel_rate(info)
    if pixel_rate <= 0 or info.duration_sec <= 0 or not math.isfinite(info.duration_sec):
        return 0
    video_bps = TARGET_BPP[target_codec] * pixel_rate
    audio_bps = _AUDIO_ESTIMATE_BPS if info.audio_codec else 0.0
    return int((video_bps + audio_bps) * info.duration_sec / 8.0)


def _compress_plan(info: VideoInfo, codec_key: str, reason: str) -> VideoOptimizeResult:
    result = _base_analysis(info)
    result.action = "video.compress"
    result.recommended = f"{codec_key} (web preset)"
    result.reason = reason
    result.estimated_bytes = _estimate_video_bytes(info, codec_key)
    result.plan = {
        "command": "video.compress",
        "arguments": {"preset": "web", "codec": codec_key},
    }
    return result


def _convert_plan(info: VideoInfo, codec_key: str, reason: str) -> VideoOptimizeResult:
    result = _base_analysis(info)
    container = VIDEO_CODECS[codec_key][1]
    result.action = "video.convert"
    result.recommended = f"{codec_key}/{container}"
    result.reason = reason
    result.estimated_bytes = _estimate_video_bytes(info, codec_key)
    result.plan = {
        "command": "video.convert",
        "arguments": {"to": container, "codec": codec_key},
    }
    return result


def _keep_plan(info: VideoInfo, reason: str) -> VideoOptimizeResult:
    result = _base_analysis(info)
    result.action = "keep"
    result.recommended = "keep"
    result.reason = reason
    result.plan = {"command": "keep", "arguments": {}}
    return result


def _base_analysis(info: VideoInfo) -> VideoOptimizeResult:
    pixel_rate = _pixel_rate(info)
    bpp = 0.0
    if pixel_rate > 0 and info.bit_rate > 0:
        ratio = info.bit_rate / pixel_rate
        # A subnormal pixel rate (crafted avg_frame_rate fractions can get
        # arbitrarily close to zero) overflows the division to infinity;
        # treat that as "no usable signal" rather than emitting inf.
        bpp = ratio if math.isfinite(ratio) else 0.0
    return VideoOptimizeResult(
        input_path=info.path,
        input_bytes=info.size_bytes,
        duration_sec=info.duration_sec,
        width=info.width,
        height=info.height,
        video_codec=info.video_codec,
        bits_per_pixel=round(bpp, 4),
    )


def analyze_video_info(info: VideoInfo) -> VideoOptimizeResult:
    """Turn one ffprobe result into a deterministic optimize recommendation.

    Pure decision logic (unit-testable without ffmpeg): legacy codecs are
    modernised, wasteful bitrates are re-encoded in the same codec family,
    fat unknown intermediates go to H.264, and everything else is kept
    untouched — re-encoding an already-efficient file only loses quality.
    """
    codec = info.video_codec
    bpp = _base_analysis(info).bits_per_pixel

    if codec in LEGACY_VIDEO_CODECS:
        # vp8 lives in webm land; everything else modernises to h264.
        codec_key = "vp9" if codec == "vp8" else "h264"
        reason = f"陈旧编码 {codec}，现代化转码可大幅瘦身"
        if Path(info.path).suffix.lower() in MODERN_CONTAINER_SUFFIXES:
            # The container is already fine: a compress derivative avoids
            # colliding with the source name the way convert-to-same-ext would.
            return _compress_plan(info, codec_key, reason)
        return _convert_plan(info, codec_key, reason)

    codec_key = _MODERN_CODEC_KEYS.get(codec, "")
    if codec_key:
        if bpp <= 0:
            return _keep_plan(info, "探测信号不足（缺码率或帧率），保守起见不重编码")
        if bpp > WORTHWHILE_BPP[codec_key]:
            saving = 1.0 - TARGET_BPP[codec_key] / bpp
            reason = f"码率偏高（{bpp:.2f} bpp，{codec}），web 预设重压预计可省约 {saving:.0%}"
            return _compress_plan(info, codec_key, reason)
        return _keep_plan(info, f"编码效率已良好（{bpp:.2f} bpp，{codec}），重压收益有限")

    if bpp > INTERMEDIATE_BPP:
        return _convert_plan(
            info, "h264", f"高码率中间格式 {codec}（{bpp:.2f} bpp），转 H.264 通用且小"
        )
    return _keep_plan(info, f"未识别的编码 {codec or '?'} 且码率不高，保守起见不重编码")


# ============================================================
#  Runtime (needs ffmpeg/ffprobe)
# ============================================================


def _ffprobe_fps(rate: str) -> float:
    """Parse an ffprobe ``avg_frame_rate`` fraction like ``30000/1001``."""
    if not rate or rate in ("0/0", "0"):
        return 0.0
    if "/" in rate:
        num, _, den = rate.partition("/")
        try:
            denominator = float(den)
            value = float(num) / denominator if denominator else 0.0
        except (ValueError, OverflowError):
            return 0.0
    else:
        try:
            value = float(rate)
        except ValueError:
            return 0.0
    return value if math.isfinite(value) and value >= 0 else 0.0


def probe(path: str) -> VideoInfo:
    """Return a VideoInfo for ``path`` using ffprobe."""
    info = VideoInfo(path=path)
    if not os.path.exists(path):
        info.exists = False
        info.error = "input_not_found"
        return info
    check_ffmpeg()
    info.size_bytes = os.path.getsize(path)
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                "-show_data_hash",
                "sha256",
                _safe_path(path),
            ],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=PROBE_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        info.error = "probe_timeout"
        return info
    if completed.returncode != 0:
        info.error = "probe_failed"
        return info
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError:
        info.error = "probe_unparsable"
        return info

    streams = data.get("streams", [])
    info.stream_count = len(streams)
    container_format = data.get("format", {})
    info.container = str(container_format.get("format_name", ""))
    try:
        info.duration_sec = float(container_format.get("duration", 0.0))
    except (TypeError, ValueError):
        info.duration_sec = 0.0
    if not math.isfinite(info.duration_sec) or info.duration_sec < 0:
        # Non-finite durations would crash size estimates and serialize as
        # invalid JSON (Infinity); treat them as "no signal".
        info.duration_sec = 0.0
    try:
        info.bit_rate = int(container_format.get("bit_rate", 0))
    except (TypeError, ValueError):
        info.bit_rate = 0
    for stream in streams:
        kind = stream.get("codec_type")
        if kind == "video" and not info.video_codec:
            if bool((stream.get("disposition") or {}).get("attached_pic", 0)):
                continue
            info.video_codec = str(stream.get("codec_name", ""))
            info.video_profile = str(stream.get("profile", ""))
            try:
                info.video_level = int(stream.get("level", 0) or 0)
            except (TypeError, ValueError):
                info.video_level = 0
            info.pixel_format = str(stream.get("pix_fmt", ""))
            info.frame_rate = str(stream.get("avg_frame_rate", ""))
            info.video_time_base = str(stream.get("time_base", ""))
            info.sample_aspect_ratio = str(stream.get("sample_aspect_ratio", ""))
            info.field_order = str(stream.get("field_order", ""))
            info.video_extradata_hash = str(stream.get("extradata_hash", ""))
            info.color_range = str(stream.get("color_range", ""))
            info.color_space = str(stream.get("color_space", ""))
            info.color_primaries = str(stream.get("color_primaries", ""))
            info.color_transfer = str(stream.get("color_transfer", ""))
            info.width = int(stream.get("width", 0) or 0)
            info.height = int(stream.get("height", 0) or 0)
            info.fps = _ffprobe_fps(str(stream.get("avg_frame_rate", "0/0")))
        elif kind == "audio" and not info.audio_codec:
            info.audio_codec = str(stream.get("codec_name", ""))
            try:
                info.audio_sample_rate = int(stream.get("sample_rate", 0) or 0)
            except (TypeError, ValueError):
                info.audio_sample_rate = 0
            try:
                info.audio_channels = int(stream.get("channels", 0) or 0)
            except (TypeError, ValueError):
                info.audio_channels = 0
            info.audio_channel_layout = str(stream.get("channel_layout", ""))
            info.audio_sample_format = str(stream.get("sample_fmt", ""))
            info.audio_time_base = str(stream.get("time_base", ""))
    return info


def run_ffmpeg(args: list[str], *, timeout: float = DEFAULT_RUN_TIMEOUT_S) -> tuple[int, str]:
    """Run one ffmpeg invocation; return ``(returncode, stderr_tail)``.

    stderr is drained on a background thread so a chatty encoder cannot fill
    the pipe and deadlock. stdin is closed to keep ffmpeg non-interactive.
    """
    check_ffmpeg()
    command = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *args]
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        start_new_session=os.name == "posix",
    )
    captured: deque[str] = deque(maxlen=5)

    def _kill_process_group() -> None:
        if os.name == "posix" and getattr(process, "pid", None) is not None:
            try:
                # These members do not exist in Windows' typeshed surface,
                # although this branch is guarded to POSIX at runtime.
                os_module: Any = os
                signal_module: Any = signal
                os_module.killpg(os_module.getpgid(process.pid), signal_module.SIGKILL)
                return
            except OSError:
                pass
        with suppress(OSError):
            process.kill()

    def _drain() -> None:
        if process.stderr is not None:
            for line in process.stderr:
                captured.append(line)

    thread = threading.Thread(target=_drain, daemon=True)
    thread.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_group()
        with suppress(OSError, subprocess.TimeoutExpired):
            process.wait(timeout=1.0)
        thread.join(timeout=1.0)
        return 124, "ffmpeg_timeout"
    except BaseException:
        # KeyboardInterrupt/SystemExit must not leave ffmpeg encoding after the
        # PixShift caller has stopped or while an atomic temp path is removed.
        _kill_process_group()
        with suppress(OSError, subprocess.TimeoutExpired):
            process.wait(timeout=1.0)
        thread.join(timeout=1.0)
        raise
    thread.join(timeout=1.0)
    tail = "".join(captured).strip()
    return process.returncode, tail


def collect_video_files(input_paths: list[str], recursive: bool = False) -> list[str]:
    """Collect video files from files and directories."""
    files: list[str] = []
    for path_str in input_paths:
        path = Path(path_str)
        if path.is_file():
            if path.suffix.lower() in VIDEO_INPUT_FORMATS:
                files.append(str(path.resolve()))
        elif path.is_dir():
            pattern = "**/*" if recursive else "*"
            for item in sorted(path.glob(pattern)):
                if (
                    not item.is_symlink()
                    and item.is_file()
                    and item.suffix.lower() in VIDEO_INPUT_FORMATS
                ):
                    files.append(str(item.resolve()))
    return sorted(set(files))


def resolve_thumbnail_time(spec: str, duration_sec: float) -> float:
    """Resolve a ``--at`` spec (timecode or ``P%``) to absolute seconds."""
    spec = spec.strip()
    if spec.endswith("%"):
        try:
            percent = float(spec[:-1])
        except ValueError as error:
            raise ValueError("invalid_thumbnail_at") from error
        if not 0 <= percent <= 100:
            raise ValueError("invalid_thumbnail_at")
        return max(0.0, duration_sec * percent / 100.0)
    return parse_timecode(spec)
