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
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

PROBE_TIMEOUT_S = 20.0
DEFAULT_RUN_TIMEOUT_S = 3600.0

DEFAULT_VIDEO_CONTAINER = "mp4"
DEFAULT_VIDEO_PRESET = "web"
DEFAULT_VIDEO_CODEC = "h264"
DEFAULT_AUDIO_FORMAT = "mp3"
DEFAULT_THUMBNAIL_AT = "25%"
DEFAULT_GIF_FPS = 12
DEFAULT_GIF_WIDTH = 480

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
    audio_codec: str = ""
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
    if any(number < 0 for number in numbers):
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


def build_convert_args(
    src: str, dst: str, *, container: str, codec: str | None = None
) -> list[str]:
    """Argv to transcode ``src`` into ``container`` (default codec per container)."""
    container = container.lower().lstrip(".")
    codec_key = codec or CONTAINER_DEFAULT_CODEC.get(container, "h264")
    if codec_key not in VIDEO_CODECS:
        raise ValueError(f"unsupported_video_codec:{codec_key}")
    encoder, _default_container, audio_encoder = VIDEO_CODECS[codec_key]
    args = ["-i", _safe_path(src), "-c:v", encoder]
    if codec_key in ("h264", "h265"):
        args += ["-crf", "23", "-preset", "medium"]
        if codec_key == "h265":
            args += ["-tag:v", "hvc1"]
    elif codec_key == "vp9":
        args += ["-crf", "33", "-b:v", "0"]
    elif codec_key == "av1":
        args += ["-crf", "35", "-preset", "8"]
    args += ["-c:a", audio_encoder, "-b:a", "128k"]
    if container in ("mp4", "mov"):
        args += ["-movflags", "+faststart"]
    args.append(_safe_path(dst))
    return args


def build_compress_args(
    src: str, dst: str, *, preset: str, codec: str, crf: int | None = None
) -> list[str]:
    """Argv to compress ``src`` using a preset/codec, optional CRF override."""
    if preset not in VIDEO_COMPRESS_PRESETS:
        raise ValueError(f"unsupported_video_preset:{preset}")
    if codec not in VIDEO_CODECS:
        raise ValueError(f"unsupported_video_codec:{codec}")
    knobs = VIDEO_COMPRESS_PRESETS[preset][codec]
    encoder, _container, audio_encoder = VIDEO_CODECS[codec]
    effective_crf = crf if crf is not None else int(knobs["crf"])
    args = ["-i", _safe_path(src), "-c:v", encoder, "-crf", str(effective_crf)]
    if "preset" in knobs:
        args += ["-preset", str(knobs["preset"])]
    if codec == "vp9":
        args += ["-b:v", "0"]
    if codec == "h265":
        args += ["-tag:v", "hvc1"]
    if preset == "tiny":
        # Cap the long edge; -2 keeps the other dimension even for the encoder.
        args += ["-vf", "scale='min(1280,iw)':-2"]
    args += ["-c:a", audio_encoder, "-b:a", "128k"]
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
    args = ["-ss", f"{start:.3f}", "-i", _safe_path(src)]
    if end is not None:
        args += ["-to", f"{end:.3f}"]
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
    args = ["-i", _safe_path(src), "-vn", "-c:a", encoder]
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
    args = ["-ss", f"{start:.3f}", "-i", _safe_path(src)]
    if duration is not None:
        if duration <= 0:
            raise ValueError("gif_duration_must_be_positive")
        args += ["-t", f"{duration:.3f}"]
    # Numbers are validated ints/floats above, never raw user strings.
    filtergraph = (
        f"fps={fps},scale={width}:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse"
    )
    args += ["-filter_complex", filtergraph, "-loop", "0", _safe_path(dst)]
    return args


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
            return float(num) / denominator if denominator else 0.0
        except ValueError:
            return 0.0
    try:
        return float(rate)
    except ValueError:
        return 0.0


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
    try:
        info.bit_rate = int(container_format.get("bit_rate", 0))
    except (TypeError, ValueError):
        info.bit_rate = 0
    for stream in streams:
        kind = stream.get("codec_type")
        if kind == "video" and not info.video_codec:
            info.video_codec = str(stream.get("codec_name", ""))
            info.width = int(stream.get("width", 0) or 0)
            info.height = int(stream.get("height", 0) or 0)
            info.fps = _ffprobe_fps(str(stream.get("avg_frame_rate", "0/0")))
        elif kind == "audio" and not info.audio_codec:
            info.audio_codec = str(stream.get("codec_name", ""))
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
    )
    captured: list[str] = []

    def _drain() -> None:
        if process.stderr is not None:
            for line in process.stderr:
                captured.append(line)

    thread = threading.Thread(target=_drain, daemon=True)
    thread.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        thread.join(timeout=1.0)
        return 124, "ffmpeg_timeout"
    thread.join(timeout=1.0)
    tail = "".join(captured[-5:]).strip()
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
                if item.is_file() and item.suffix.lower() in VIDEO_INPUT_FORMATS:
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
