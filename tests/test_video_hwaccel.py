"""Tests for opt-in hardware-accelerated video encoding (pure argv layer)."""

import json

import pytest
from click.testing import CliRunner

from pixshift.cli import cli
from pixshift.video_engine import build_compress_args, build_convert_args


def test_convert_nvenc_swaps_encoder_and_quality_knobs():
    args = build_convert_args("/a/in.mov", "/a/out.mp4", container="mp4", hwaccel="nvenc")
    assert "h264_nvenc" in args
    assert "libx264" not in args
    assert "-crf" not in args
    assert args[args.index("-cq") + 1] == "23"
    assert args[args.index("-rc") + 1] == "vbr"
    assert args[args.index("-preset") + 1] == "p5"
    assert "+faststart" in args


def test_convert_videotoolbox_maps_crf_onto_qv():
    args = build_convert_args(
        "/a/in.mov", "/a/out.mp4", container="mp4", codec="h265", hwaccel="videotoolbox"
    )
    assert "hevc_videotoolbox" in args
    # CRF 23 -> (51 - 23) * 2 = 56 on the 1..100 -q:v scale.
    assert args[args.index("-q:v") + 1] == "56"
    assert "-preset" not in args
    assert args[args.index("-tag:v") + 1] == "hvc1"


def test_compress_qsv_uses_global_quality_and_keeps_preset_names():
    args = build_compress_args(
        "/a/in.mp4", "/a/out.mp4", preset="archive", codec="h264", hwaccel="qsv"
    )
    assert "h264_qsv" in args
    assert args[args.index("-global_quality") + 1] == "18"
    assert args[args.index("-preset") + 1] == "slow"


def test_compress_nvenc_translates_speed_preset_and_crf_override():
    args = build_compress_args(
        "/a/in.mp4", "/a/out.mp4", preset="archive", codec="h265", crf=30, hwaccel="nvenc"
    )
    assert "hevc_nvenc" in args
    assert args[args.index("-cq") + 1] == "30"
    assert args[args.index("-preset") + 1] == "p6"
    assert args[args.index("-tag:v") + 1] == "hvc1"


def test_compress_tiny_keeps_software_downscale_with_hw_encode():
    args = build_compress_args(
        "/a/in.mp4", "/a/out.mp4", preset="tiny", codec="h264", hwaccel="videotoolbox"
    )
    assert "h264_videotoolbox" in args
    assert "scale='min(1280,iw)':-2" in args
    # tiny h264 CRF 32 -> (51 - 32) * 2 = 38.
    assert args[args.index("-q:v") + 1] == "38"


def test_videotoolbox_quality_clamps_to_valid_range():
    args = build_compress_args(
        "/a/in.mp4", "/a/out.mp4", preset="web", codec="h264", crf=51, hwaccel="videotoolbox"
    )
    assert args[args.index("-q:v") + 1] == "1"
    args = build_compress_args(
        "/a/in.mp4", "/a/out.mp4", preset="web", codec="h264", crf=0, hwaccel="videotoolbox"
    )
    assert args[args.index("-q:v") + 1] == "100"


@pytest.mark.parametrize("codec", ["vp9", "av1"])
def test_hwaccel_rejects_unmapped_codec_families(codec):
    with pytest.raises(ValueError, match=f"unsupported_hwaccel:nvenc:{codec}"):
        build_compress_args("/a/i.mp4", "/a/o.webm", preset="web", codec=codec, hwaccel="nvenc")


def test_hwaccel_rejects_unknown_backend():
    with pytest.raises(ValueError, match="unsupported_hwaccel:cuda:h264"):
        build_convert_args("/a/i.mp4", "/a/o.mp4", container="mp4", hwaccel="cuda")


def test_software_paths_are_unchanged_without_hwaccel():
    args = build_convert_args("/a/in.mov", "/a/out.mp4", container="mp4")
    assert "libx264" in args
    assert args[args.index("-crf") + 1] == "23"
    args = build_compress_args("/a/in.mp4", "/a/o.webm", preset="web", codec="vp9")
    assert "libvpx-vp9" in args
    assert "-b:v" in args


# ------------------------------------------------------------------
# CLI plumbing (ops layer faked; no ffmpeg needed)
# ------------------------------------------------------------------


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def clip(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fake video bytes")
    return source


@pytest.fixture
def ffmpeg_ready(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        with open(args[-1], "wb") as handle:
            handle.write(b"encoded-output")
        return 0, ""

    monkeypatch.setattr("pixshift.ops.video.FFMPEG_AVAILABLE", True)
    monkeypatch.setattr("pixshift.ops.video.run_ffmpeg", fake_run)
    return calls


def test_cli_convert_passes_hwaccel_through(runner, ffmpeg_ready, clip):
    result = runner.invoke(
        cli, ["video", "convert", str(clip), "-t", "mkv", "--hwaccel", "nvenc", "--json"]
    )
    assert result.exit_code == 0
    argv = ffmpeg_ready[0]
    assert "hevc_nvenc" in argv  # mkv defaults to the h265 family
    assert "-cq" in argv


def test_cli_compress_passes_hwaccel_through(runner, ffmpeg_ready, clip):
    result = runner.invoke(cli, ["video", "compress", str(clip), "--hwaccel", "qsv", "--json"])
    assert result.exit_code == 0
    argv = ffmpeg_ready[0]
    assert "h264_qsv" in argv
    assert "-global_quality" in argv


def test_cli_hwaccel_with_unmapped_codec_is_a_stable_error(runner, ffmpeg_ready, clip):
    result = runner.invoke(
        cli,
        ["video", "compress", str(clip), "--codec", "vp9", "--hwaccel", "nvenc", "--json"],
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["results"][0]["error"] == "unsupported_hwaccel:nvenc:vp9"


def test_cli_rejects_unknown_hwaccel_backend(runner, ffmpeg_ready, clip):
    result = runner.invoke(cli, ["video", "convert", str(clip), "--hwaccel", "cuda"])
    assert result.exit_code == 2  # click choice validation
