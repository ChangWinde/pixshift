"""Property-based tests for the agent-facing pure contracts.

These functions parse untrusted input (timecodes, ffprobe output, JPEG bytes,
plan documents) or generate ffmpeg argv, so they are held to total-function
invariants: never crash, never emit non-finite numbers, never produce a
malformed structure. The deterministic profile keeps CI stable.
"""

import io
import json
import math
import os

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from PIL import Image

from pixshift.ops.apply import load_plan_document
from pixshift.pdf_engine import _strip_jpeg_metadata
from pixshift.video_engine import (
    HWACCEL_BACKENDS,
    VIDEO_CODECS,
    VIDEO_COMPRESS_PRESETS,
    VideoInfo,
    _ffprobe_fps,
    analyze_video_info,
    build_compress_args,
    build_convert_args,
    parse_timecode,
    resolve_thumbnail_time,
)

settings.register_profile(
    "pixshift",
    derandomize=True,
    max_examples=80,
    suppress_health_check=[HealthCheck.too_slow],
)
# Randomized deep exploration for manual fuzz campaigns:
#   PIXSHIFT_HYPOTHESIS_PROFILE=stress uv run pytest tests/test_property_contracts.py
settings.register_profile(
    "stress",
    derandomize=False,
    max_examples=1500,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
settings.load_profile(os.environ.get("PIXSHIFT_HYPOTHESIS_PROFILE", "pixshift"))


# ------------------------------------------------------------------
# Timecodes and probe parsing
# ------------------------------------------------------------------


@given(st.text(max_size=30))
def test_parse_timecode_is_total(text):
    try:
        seconds = parse_timecode(text)
    except ValueError as error:
        assert str(error) == "invalid_timecode"
    else:
        assert math.isfinite(seconds)
        assert seconds >= 0


@given(
    st.integers(min_value=0, max_value=59),
    st.integers(min_value=0, max_value=59),
)
def test_parse_timecode_minutes_algebra(minutes, seconds):
    assert parse_timecode(f"{minutes}:{seconds}") == pytest.approx(minutes * 60 + seconds)


@given(
    st.floats(min_value=0, max_value=100, allow_nan=False),
    st.floats(min_value=0, max_value=86400, allow_nan=False),
)
def test_thumbnail_percent_stays_within_duration(percent, duration):
    resolved = resolve_thumbnail_time(f"{percent}%", duration)
    assert 0 <= resolved <= duration + 1e-6


@given(st.text(max_size=30))
def test_thumbnail_spec_is_total(spec):
    try:
        resolved = resolve_thumbnail_time(spec, 120.0)
    except ValueError:
        pass
    else:
        assert math.isfinite(resolved)
        assert resolved >= 0


@given(st.text(max_size=20))
def test_ffprobe_fps_is_total(rate):
    value = _ffprobe_fps(rate)
    assert math.isfinite(value)
    assert value >= 0


# ------------------------------------------------------------------
# Video optimize analysis
# ------------------------------------------------------------------

_video_infos = st.builds(
    VideoInfo,
    path=st.sampled_from(["/m/a.mp4", "/m/b.webm", "/m/c.avi", "/m/d.mov"]),
    duration_sec=st.floats(allow_nan=False, min_value=-10, max_value=1e12),
    width=st.integers(min_value=-10, max_value=10000),
    height=st.integers(min_value=-10, max_value=10000),
    video_codec=st.sampled_from(
        ["h264", "hevc", "vp9", "av1", "mpeg4", "vp8", "prores", "mysterycodec", ""]
    ),
    audio_codec=st.sampled_from(["aac", "opus", ""]),
    fps=st.floats(allow_nan=False, min_value=-5, max_value=1000),
    bit_rate=st.integers(min_value=-1, max_value=10**12),
    size_bytes=st.integers(min_value=0, max_value=10**12),
)


@given(_video_infos)
def test_video_analysis_is_total_and_well_formed(info):
    result = analyze_video_info(info)
    assert result.action in ("video.convert", "video.compress", "keep")
    assert result.plan["command"] == result.action
    assert isinstance(result.plan["arguments"], dict)
    assert isinstance(result.estimated_bytes, int)
    assert result.estimated_bytes >= 0
    assert math.isfinite(result.bits_per_pixel)
    if result.action == "keep":
        assert result.estimated_bytes == 0
    else:
        codec = result.plan["arguments"].get("codec", "")
        assert codec in VIDEO_CODECS


# ------------------------------------------------------------------
# JPEG metadata strip (untrusted bytes)
# ------------------------------------------------------------------


@given(st.binary(max_size=4096))
def test_jpeg_strip_never_raises_on_arbitrary_bytes(data):
    stripped = _strip_jpeg_metadata(data)
    assert stripped is None or stripped.startswith(b"\xff\xd8")


@given(
    st.integers(min_value=8, max_value=64),
    st.integers(min_value=8, max_value=64),
    st.integers(min_value=20, max_value=95),
    st.booleans(),
    st.booleans(),
)
def test_jpeg_strip_is_pixel_lossless_on_real_jpegs(width, height, quality, exif, comment):
    img = Image.new("RGB", (width, height), (width * 3 % 255, height * 2 % 255, 99))
    params = {"format": "JPEG", "quality": quality}
    if exif:
        tags = Image.Exif()
        tags[271] = "PixCam"
        params["exif"] = tags.tobytes()
    if comment:
        params["comment"] = b"note"
    buffer = io.BytesIO()
    img.save(buffer, **params)
    raw = buffer.getvalue()

    stripped = _strip_jpeg_metadata(raw)
    assert stripped is not None
    assert len(stripped) <= len(raw)
    assert b"Exif" not in stripped
    with Image.open(io.BytesIO(raw)) as before, Image.open(io.BytesIO(stripped)) as after:
        assert before.tobytes() == after.tobytes()


# ------------------------------------------------------------------
# Plan document normalization (untrusted JSON)
# ------------------------------------------------------------------

_json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(max_size=12),
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=8), children, max_size=4)
    ),
    max_leaves=12,
)


@given(_json_values)
def test_plan_loading_is_total(document):
    raw = json.dumps(document)
    try:
        steps = load_plan_document(raw)
    except ValueError:
        return
    assert isinstance(steps, list)
    for step in steps:
        assert isinstance(step["input"], str) and step["input"]
        assert isinstance(step["command"], str) and step["command"]
        assert isinstance(step["arguments"], dict)


# ------------------------------------------------------------------
# ffmpeg argv builders
# ------------------------------------------------------------------


@given(
    st.sampled_from(["mp4", "webm", "mkv", "mov"]),
    st.sampled_from([None, *VIDEO_CODECS]),
    st.sampled_from([None, *HWACCEL_BACKENDS]),
)
def test_convert_argv_shape(container, codec, hwaccel):
    try:
        args = build_convert_args(
            "/in/clip.src", "/out/clip.dst", container=container, codec=codec, hwaccel=hwaccel
        )
    except ValueError as error:
        assert str(error).startswith("unsupported_hwaccel:")
        return
    assert all(isinstance(part, str) and part for part in args)
    assert args[-1].endswith("clip.dst")
    assert ("-crf" in args) == (hwaccel is None)


@given(
    st.sampled_from(list(VIDEO_COMPRESS_PRESETS)),
    st.sampled_from(list(VIDEO_CODECS)),
    st.one_of(st.none(), st.integers(min_value=0, max_value=63)),
    st.sampled_from([None, *HWACCEL_BACKENDS]),
)
def test_compress_argv_shape(preset, codec, crf, hwaccel):
    try:
        args = build_compress_args(
            "/in/clip.src", "/out/clip.dst", preset=preset, codec=codec, crf=crf, hwaccel=hwaccel
        )
    except ValueError as error:
        assert str(error).startswith("unsupported_hwaccel:")
        return
    assert all(isinstance(part, str) and part for part in args)
    assert args[-1].endswith("clip.dst")
    assert ("-tag:v" in args) == (codec == "h265")
    if hwaccel is None and crf is not None:
        assert args[args.index("-crf") + 1] == str(crf)
