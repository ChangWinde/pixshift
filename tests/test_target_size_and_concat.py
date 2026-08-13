"""Tests for the size-budget story (video/pdf --target-size) and video concat."""

import json
import os

import pytest
from click.testing import CliRunner
from PIL import Image

from pixshift.cli import cli
from pixshift.compress_engine import parse_target_size
from pixshift.ops import video as video_ops
from pixshift.pdf_engine import pdf_compress_to_target, pdf_merge_images
from pixshift.video_engine import (
    MIN_TARGET_VIDEO_BPS,
    VideoInfo,
    build_bitrate_pass_args,
    build_concat_args,
    compute_target_video_bitrate,
    concat_list_content,
)

# ------------------------------------------------------------------
# Pure math and argv builders
# ------------------------------------------------------------------


def test_target_bitrate_budget_math():
    # 25MB over 100s with audio: (25*8*1024*1024/100)*0.98 - 128000
    bps = compute_target_video_bitrate(25 * 1024 * 1024, 100.0, has_audio=True)
    assert bps == int(25 * 1024 * 1024 * 8 / 100 * 0.98 - 128_000)
    silent = compute_target_video_bitrate(25 * 1024 * 1024, 100.0, has_audio=False)
    assert silent == bps + 128_000


def test_target_bitrate_rejects_bad_signals():
    assert compute_target_video_bitrate(0, 100.0, has_audio=True) == 0
    assert compute_target_video_bitrate(1024, 0.0, has_audio=True) == 0
    assert compute_target_video_bitrate(1024, float("inf"), has_audio=True) == 0
    # Tiny budget over a long duration collapses below zero once audio is paid.
    assert compute_target_video_bitrate(1024, 3600.0, has_audio=True) == 0


def test_two_pass_argv_shapes():
    first = build_bitrate_pass_args(
        "/in/a.mp4",
        "/out/b.mp4",
        codec="h264",
        video_bps=1_000_000,
        has_audio=True,
        pass_number=1,
        passlog="/tmp/log",
    )
    assert "-pass" in first and first[first.index("-pass") + 1] == "1"
    assert "-an" in first
    assert first[-1] == os.devnull
    assert "-c:a" not in first

    second = build_bitrate_pass_args(
        "/in/a.mp4",
        "/out/b.mp4",
        codec="h264",
        video_bps=1_000_000,
        has_audio=True,
        pass_number=2,
        passlog="/tmp/log",
    )
    assert second[second.index("-pass") + 1] == "2"
    assert second[second.index("-b:v") + 1] == "1000000"
    assert "-c:a" in second
    assert second[-1].endswith("b.mp4")

    single = build_bitrate_pass_args(
        "/in/a.mp4",
        "/out/b.mp4",
        codec="h264",
        video_bps=500_000,
        has_audio=False,
        pass_number=None,
        passlog="/tmp/log",
        hwaccel="nvenc",
    )
    assert "h264_nvenc" in single
    assert "-pass" not in single
    assert "-an" in single


def test_concat_list_escapes_quotes(tmp_path):
    tricky = tmp_path / "it's a clip.mp4"
    tricky.write_bytes(b"x")
    plain = tmp_path / "b.mp4"
    plain.write_bytes(b"y")
    content = concat_list_content([str(tricky), str(plain)])
    lines = content.strip().splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("file '")
    assert "'\\''" in lines[0]


def test_concat_argv_modes():
    copy = build_concat_args("/tmp/list.txt", "/out/j.mp4")
    assert copy[copy.index("-f") + 1] == "concat"
    assert "copy" in copy
    assert "+faststart" in copy
    reencode = build_concat_args("/tmp/list.txt", "/out/j.mkv", reencode=True)
    assert "libx264" in reencode
    assert "+faststart" not in reencode


# ------------------------------------------------------------------
# Video ops orchestration (runtime faked)
# ------------------------------------------------------------------


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def clip(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"x" * (3 * 1024 * 1024))
    return source


def _install_probe(monkeypatch, *, duration=10.0, audio="aac"):
    def fake_probe(path):
        return VideoInfo(
            path=path,
            duration_sec=duration,
            width=1280,
            height=720,
            video_codec="h264",
            audio_codec=audio,
            fps=30.0,
            bit_rate=4_000_000,
            container="mp4",
            stream_count=2,
            size_bytes=os.path.getsize(path),
        )

    monkeypatch.setattr("pixshift.ops.video.FFMPEG_AVAILABLE", True)
    monkeypatch.setattr("pixshift.ops.video.probe", fake_probe)


def test_target_size_runs_two_passes(monkeypatch, clip, tmp_path):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        if args[-1] != os.devnull:
            with open(args[-1], "wb") as handle:
                handle.write(b"v" * 512)  # under the 1KB target
        return 0, ""

    _install_probe(monkeypatch)
    monkeypatch.setattr("pixshift.ops.video.run_ffmpeg", fake_run)
    result = video_ops.compress_to_target_one(
        str(clip), str(tmp_path / "out.mp4"), target_bytes=1024 * 1024
    )
    assert result.success is True, result.error
    assert len(calls) == 2
    assert calls[0][calls[0].index("-pass") + 1] == "1"
    assert calls[1][calls[1].index("-pass") + 1] == "2"
    assert result.detail.startswith("video_bitrate_")


def test_target_size_retries_then_reports_miss(monkeypatch, clip, tmp_path):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        if args[-1] != os.devnull:
            with open(args[-1], "wb") as handle:
                handle.write(b"v" * (2 * 1024 * 1024))  # always over the 1MB target
        return 0, ""

    _install_probe(monkeypatch)
    monkeypatch.setattr("pixshift.ops.video.run_ffmpeg", fake_run)
    result = video_ops.compress_to_target_one(
        str(clip), str(tmp_path / "out.mp4"), target_bytes=1024 * 1024
    )
    assert result.success is False
    assert result.error == "target_size_missed"
    assert len(calls) == 4  # two passes x two attempts
    assert not (tmp_path / "out.mp4").exists()


def test_target_size_copies_when_already_small(monkeypatch, clip, tmp_path):
    _install_probe(monkeypatch)
    monkeypatch.setattr(
        "pixshift.ops.video.run_ffmpeg",
        lambda *a, **k: pytest.fail("must not encode"),
    )
    result = video_ops.compress_to_target_one(
        str(clip), str(tmp_path / "out.mp4"), target_bytes=4 * 1024 * 1024
    )
    assert result.success is True
    assert result.detail == "already_within_target"
    assert (tmp_path / "out.mp4").read_bytes() == clip.read_bytes()


def test_target_size_rejects_impossible_budget(monkeypatch, clip, tmp_path):
    _install_probe(monkeypatch, duration=3600.0)
    result = video_ops.compress_to_target_one(
        str(clip), str(tmp_path / "out.mp4"), target_bytes=2048
    )
    assert result.success is False
    assert result.error == "target_size_too_small"
    assert MIN_TARGET_VIDEO_BPS > 0


def test_target_size_needs_duration(monkeypatch, clip, tmp_path):
    _install_probe(monkeypatch, duration=0.0)
    result = video_ops.compress_to_target_one(
        str(clip), str(tmp_path / "out.mp4"), target_bytes=1024
    )
    assert result.error == "no_duration_signal"


def test_cli_target_size_conflicts_are_usage_errors(runner, monkeypatch, clip):
    monkeypatch.setattr("pixshift.ops.video.FFMPEG_AVAILABLE", True)
    with_crf = runner.invoke(
        cli,
        ["video", "compress", str(clip), "--target-size", "1MB", "--crf", "30", "--json"],
    )
    assert with_crf.exit_code == 2
    assert json.loads(with_crf.output)["error"] == "conflicting_options"

    with_preset = runner.invoke(
        cli,
        ["video", "compress", str(clip), "--target-size", "1MB", "-p", "tiny", "--json"],
    )
    assert with_preset.exit_code == 2

    bad_size = runner.invoke(
        cli, ["video", "compress", str(clip), "--target-size", "huge", "--json"]
    )
    assert bad_size.exit_code == 2
    assert json.loads(bad_size.output)["error"] == "invalid_target_size"


def test_cli_target_size_end_to_end(runner, monkeypatch, clip, tmp_path):
    def fake_run(args, **kwargs):
        if args[-1] != os.devnull:
            with open(args[-1], "wb") as handle:
                handle.write(b"v" * 100)
        return 0, ""

    _install_probe(monkeypatch)
    monkeypatch.setattr("pixshift.ops.video.run_ffmpeg", fake_run)
    result = runner.invoke(cli, ["video", "compress", str(clip), "--target-size", "1MB", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["results"][0]["output"].endswith("clip_compressed.mp4")


def test_concat_requires_matching_streams(monkeypatch, tmp_path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    a.write_bytes(b"a")
    b.write_bytes(b"b")

    def fake_probe(path):
        codec = "h264" if path.endswith("a.mp4") else "vp9"
        return VideoInfo(
            path=path,
            duration_sec=5.0,
            width=640,
            height=360,
            video_codec=codec,
            audio_codec="aac",
            fps=30.0,
            bit_rate=1_000_000,
            container="",
            stream_count=2,
            size_bytes=1,
        )

    monkeypatch.setattr("pixshift.ops.video.FFMPEG_AVAILABLE", True)
    monkeypatch.setattr("pixshift.ops.video.probe", fake_probe)
    result = video_ops.concat_videos([str(a), str(b)], str(tmp_path / "j.mp4"))
    assert result.success is False
    assert result.error == "concat_requires_matching_streams"


def test_concat_stream_copy_success(runner, monkeypatch, tmp_path):
    a = tmp_path / "part 一.mp4"
    b = tmp_path / "part2.mp4"
    a.write_bytes(b"a" * 100)
    b.write_bytes(b"b" * 100)
    recorded = []

    def fake_run(args, **kwargs):
        recorded.append(list(args))
        with open(args[-1], "wb") as handle:
            handle.write(b"joined")
        return 0, ""

    _install_probe(monkeypatch)
    monkeypatch.setattr("pixshift.ops.video.run_ffmpeg", fake_run)
    result = runner.invoke(
        cli,
        ["video", "concat", str(a), str(b), "-o", str(tmp_path / "joined.mp4"), "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["command"] == "video.concat"
    assert payload["clips"] == 2
    assert (tmp_path / "joined.mp4").read_bytes() == b"joined"
    argv = recorded[0]
    list_path = argv[argv.index("-i") + 1]
    # The list file is cleaned up after the run, but its argv slot proves
    # the concat demuxer path was used with stream copy.
    assert "concat" in argv
    assert "copy" in argv
    assert list_path.endswith("clips.txt")


def test_concat_rejects_newline_in_filenames(monkeypatch, tmp_path):
    weird = tmp_path / "a\nb.mp4"
    plain = tmp_path / "c.mp4"
    weird.write_bytes(b"a")
    plain.write_bytes(b"b")
    _install_probe(monkeypatch)
    monkeypatch.setattr(
        "pixshift.ops.video.run_ffmpeg", lambda *a, **k: pytest.fail("must not run")
    )
    result = video_ops.concat_videos([str(weird), str(plain)], str(tmp_path / "j.mp4"))
    assert result.success is False
    assert result.error == "unsupported_path_character"


def test_concat_needs_two_inputs(runner, monkeypatch, clip, tmp_path):
    monkeypatch.setattr("pixshift.ops.video.FFMPEG_AVAILABLE", True)
    result = runner.invoke(
        cli, ["video", "concat", str(clip), "-o", str(tmp_path / "j.mp4"), "--json"]
    )
    assert result.exit_code == 2
    assert json.loads(result.output)["error"] == "concat_requires_two_inputs"


# ------------------------------------------------------------------
# PDF target size
# ------------------------------------------------------------------


def _noisy_pdf(tmp_path, count=4):
    import random

    rng = random.Random(3)
    sources = []
    for index in range(count):
        img = Image.new("RGB", (600, 400))
        img.putdata(
            [
                (rng.randrange(256), rng.randrange(256), rng.randrange(256))
                for _ in range(600 * 400 // 200)
            ]
            * 200
        )
        path = tmp_path / f"page_{index}.jpg"
        img.save(str(path), format="JPEG", quality=92)
        sources.append(str(path))
    pdf_path = tmp_path / "doc.pdf"
    result = pdf_merge_images(sources, str(pdf_path))
    assert result.success
    return pdf_path


def test_pdf_target_size_finds_highest_fitting_quality(tmp_path):
    pdf_path = _noisy_pdf(tmp_path)
    original = pdf_path.stat().st_size
    target = int(original * 0.6)
    out = tmp_path / "fit.pdf"
    result = pdf_compress_to_target(str(pdf_path), str(out), target)
    assert result.success is True, result.error
    assert out.stat().st_size <= target
    assert result.details["attempts"] >= 1
    assert result.details["target_size"] == target
    # The published quality is a concrete rung or bisection refinement.
    strategy = result.details["strategy"]
    if strategy.startswith("image_quality_"):
        quality = int(strategy.rsplit("_", 1)[1])
        assert 20 <= quality <= 95


def test_pdf_target_size_bisects_between_ladder_rungs(tmp_path):
    """The refinement must publish at least the fitting rung's quality."""
    pdf_path = _noisy_pdf(tmp_path)
    out_dir = tmp_path / "steps"
    out_dir.mkdir()
    # Establish the size at two neighbouring rungs to pick a target between
    # them, forcing the ladder to fit at the lower rung and bisect upward.
    from pixshift.pdf_engine import pdf_compress

    upper = pdf_compress(str(pdf_path), str(out_dir / "q70.pdf"), preset="medium", image_quality=70)
    lower = pdf_compress(str(pdf_path), str(out_dir / "q55.pdf"), preset="medium", image_quality=55)
    assert upper.success and lower.success
    if lower.output_size >= upper.output_size:
        pytest.skip("fixture does not separate the rungs")
    target = (lower.output_size + upper.output_size) // 2

    result = pdf_compress_to_target(str(pdf_path), str(tmp_path / "bisect.pdf"), target)
    assert result.success is True, result.error
    strategy = result.details["strategy"]
    assert strategy.startswith("image_quality_")
    quality = int(strategy.rsplit("_", 1)[1])
    assert quality >= 55
    assert (tmp_path / "bisect.pdf").stat().st_size <= target


def test_pdf_target_size_copies_when_already_small(tmp_path):
    pdf_path = _noisy_pdf(tmp_path, count=1)
    out = tmp_path / "same.pdf"
    result = pdf_compress_to_target(str(pdf_path), str(out), pdf_path.stat().st_size + 10)
    assert result.success is True
    assert result.details["strategy"] == "already_within_target"
    assert out.read_bytes() == pdf_path.read_bytes()


def test_pdf_target_size_unreachable_leaves_no_output(tmp_path):
    pdf_path = _noisy_pdf(tmp_path, count=2)
    out = tmp_path / "impossible.pdf"
    result = pdf_compress_to_target(str(pdf_path), str(out), 512)
    assert result.success is False
    assert result.error == "target_size_unreachable"
    assert result.details["closest_size"] > 512
    assert not out.exists()


def test_pdf_cli_target_size_conflicts(runner, tmp_path):
    pdf_path = _noisy_pdf(tmp_path, count=1)
    result = runner.invoke(
        cli,
        ["pdf", "compress", str(pdf_path), "--target-size", "1MB", "-p", "heavy", "--json"],
    )
    assert result.exit_code == 2
    assert json.loads(result.output)["error"] == "conflicting_options"


def test_pdf_cli_target_size_end_to_end(runner, tmp_path):
    pdf_path = _noisy_pdf(tmp_path)
    target = int(pdf_path.stat().st_size * 0.6)
    out = tmp_path / "cli_fit.pdf"
    result = runner.invoke(
        cli,
        ["pdf", "compress", str(pdf_path), "--target-size", str(target), "-o", str(out), "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["output_bytes"] <= target


def test_parse_target_size_units():
    assert parse_target_size("500KB") == 500 * 1024
    assert parse_target_size("2.5MB") == int(2.5 * 1024 * 1024)
    assert parse_target_size("1024") == 1024
    with pytest.raises(ValueError):
        parse_target_size("huge")
