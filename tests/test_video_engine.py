"""Tests for the video pillar: pure argv builders, parsing, and ffmpeg-missing."""

import json

import pytest
from click.testing import CliRunner

from pixshift.cli import cli
from pixshift.core.tool_catalog import TOOL_CATALOG
from pixshift.video_engine import (
    build_compress_args,
    build_convert_args,
    build_extract_audio_args,
    build_gif_args,
    build_thumbnail_args,
    build_trim_args,
    parse_timecode,
    resolve_thumbnail_time,
)


@pytest.mark.parametrize(
    "text,expected",
    [("90", 90.0), ("1:30", 90.0), ("0:01:30", 90.0), ("1:05:05.5", 3905.5), ("0", 0.0)],
)
def test_parse_timecode_valid(text, expected):
    assert parse_timecode(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", "  ", "1:2:3:4", "abc", "-5", "1:-2"])
def test_parse_timecode_invalid(text):
    with pytest.raises(ValueError, match="invalid_timecode"):
        parse_timecode(text)


def test_resolve_thumbnail_time_percent_and_timecode():
    assert resolve_thumbnail_time("25%", 100.0) == pytest.approx(25.0)
    assert resolve_thumbnail_time("0:10", 100.0) == pytest.approx(10.0)
    with pytest.raises(ValueError):
        resolve_thumbnail_time("150%", 100.0)


def test_build_convert_args_shape():
    args = build_convert_args("/a/in.mov", "/a/out.mp4", container="mp4")
    assert args[0] == "-i"
    assert args[1].endswith("in.mov")
    assert "libx264" in args
    assert "+faststart" in args
    assert args[-1].endswith("out.mp4")
    # No argument may be an unresolved relative/option-like token.
    assert not any(a.startswith("-") and " " in a for a in args)


def test_build_convert_args_webm_uses_vp9():
    args = build_convert_args("/a/in.mp4", "/a/out.webm", container="webm")
    assert "libvpx-vp9" in args
    assert "libopus" in args


@pytest.mark.parametrize(
    "policy,expected_codec,expected_bitrate",
    [
        ("preserve", "copy", None),
        ("compatible", "aac", "192000"),
        ("compact", "aac", "96000"),
    ],
)
def test_audio_policy_is_explicit_in_convert_argv(policy, expected_codec, expected_bitrate):
    args = build_convert_args("/a/in.mov", "/a/out.mp4", container="mp4", audio_policy=policy)
    assert args[args.index("-c:a") + 1] == expected_codec
    if expected_bitrate is None:
        assert "-b:a" not in args
    else:
        assert args[args.index("-b:a") + 1] == expected_bitrate


def test_audio_policy_rejects_unknown_value():
    with pytest.raises(ValueError, match="unsupported_audio_policy:unknown"):
        build_convert_args("/a/in.mov", "/a/out.mp4", container="mp4", audio_policy="unknown")


def test_build_compress_args_crf_override():
    args = build_compress_args("/a/in.mp4", "/a/out.mp4", preset="web", codec="h264", crf=30)
    assert "-crf" in args
    assert args[args.index("-crf") + 1] == "30"


def test_build_compress_args_tiny_scales_down():
    args = build_compress_args("/a/in.mp4", "/a/o.mp4", preset="tiny", codec="h264")
    assert "-vf" in args
    assert args[args.index("-vf") + 1] == ("scale='min(1280,iw)':-2,scale=-2:'min(1280,ih)'")


def test_build_compress_args_rejects_bad_preset_and_codec():
    with pytest.raises(ValueError):
        build_compress_args("/a/i.mp4", "/a/o.mp4", preset="nope", codec="h264")
    with pytest.raises(ValueError):
        build_compress_args("/a/i.mp4", "/a/o.mp4", preset="web", codec="nope")


def test_build_trim_args_stream_copy_and_reencode():
    copy_args = build_trim_args("/a/in.mp4", "/a/o.mp4", start=1.0, duration=5.0)
    assert "-c" in copy_args and "copy" in copy_args
    assert "-t" in copy_args
    reenc = build_trim_args("/a/in.mp4", "/a/o.mp4", start=1.0, end=6.0, reencode=True)
    assert "libx264" in reenc
    assert reenc[reenc.index("-t") + 1] == "5.000"
    assert "-to" not in reenc


def test_build_trim_args_validation():
    with pytest.raises(ValueError):
        build_trim_args("/a/i.mp4", "/a/o.mp4", start=5.0, end=3.0)
    with pytest.raises(ValueError):
        build_trim_args("/a/i.mp4", "/a/o.mp4", start=0.0, end=5.0, duration=5.0)


def test_build_thumbnail_args():
    args = build_thumbnail_args("/a/in.mp4", "/a/o.jpg", at_seconds=12.5)
    assert "-frames:v" in args
    assert args[args.index("-ss") + 1] == "12.500"


def test_build_extract_audio_args():
    args = build_extract_audio_args("/a/in.mp4", "/a/o.mp3", audio_ext="mp3")
    assert "-vn" in args
    assert "libmp3lame" in args
    with pytest.raises(ValueError):
        build_extract_audio_args("/a/in.mp4", "/a/o.xyz", audio_ext="xyz")


def test_build_gif_args_uses_palette_and_validates():
    args = build_gif_args("/a/in.mp4", "/a/o.gif", start=1.0, duration=3.0, fps=15, width=320)
    graph = args[args.index("-filter_complex") + 1]
    assert "palettegen" in graph and "paletteuse" in graph
    assert "fps=15" in graph and "scale=320" in graph
    with pytest.raises(ValueError):
        build_gif_args("/a/in.mp4", "/a/o.gif", fps=0)
    with pytest.raises(ValueError):
        build_gif_args("/a/in.mp4", "/a/o.gif", width=99999)


def test_catalog_lists_video_tools():
    names = {entry["name"] for entry in TOOL_CATALOG}
    assert {"video.info", "video.convert", "video.compress", "video.gif"} <= names


def test_video_info_reports_ffmpeg_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("pixshift.ops.video.FFMPEG_AVAILABLE", False)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"not really a video")
    result = CliRunner().invoke(cli, ["video", "info", str(clip), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output.strip())
    assert payload["error"] == "ffmpeg_missing"


def test_video_help_lists_subcommands():
    result = CliRunner().invoke(cli, ["video", "--help"])
    assert result.exit_code == 0
    for sub in ("info", "convert", "compress", "trim", "thumbnail", "gif"):
        assert sub in result.output
