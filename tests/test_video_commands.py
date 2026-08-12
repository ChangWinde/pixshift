"""Tests for the video CLI command group (ops layer faked; no ffmpeg needed)."""

import json

import pytest
from click.testing import CliRunner

from pixshift.cli import cli
from pixshift.video_engine import VideoInfo


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def clip(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fake video bytes")
    return source


def _install_probe(monkeypatch, *, error=""):
    def fake_probe(path):
        return VideoInfo(
            path=path,
            duration_sec=100.0,
            width=1920,
            height=1080,
            video_codec="h264",
            audio_codec="aac",
            fps=30.0,
            bit_rate=1_200_000,
            container="mp4",
            stream_count=2,
            size_bytes=1024,
            error=error,
        )

    monkeypatch.setattr("pixshift.ops.video.FFMPEG_AVAILABLE", True)
    monkeypatch.setattr("pixshift.ops.video.probe", fake_probe)


def test_info_json_reports_probe_fields(runner, monkeypatch, clip):
    _install_probe(monkeypatch)
    result = runner.invoke(cli, ["video", "info", str(clip), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["command"] == "video.info"
    assert payload["ok"] is True
    entry = payload["files"][0]
    assert entry["duration_sec"] == 100.0
    assert entry["width"] == 1920
    assert entry["video_codec"] == "h264"
    assert entry["error"] == ""


def test_info_human_prints_summary(runner, monkeypatch, clip):
    _install_probe(monkeypatch)
    result = runner.invoke(cli, ["video", "info", str(clip)])
    assert result.exit_code == 0
    assert "1920x1080" in result.output
    assert "h264" in result.output


def test_info_json_probe_failure_exits_nonzero(runner, monkeypatch, clip):
    _install_probe(monkeypatch, error="probe_failed")
    result = runner.invoke(cli, ["video", "info", str(clip), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["files"][0]["error"] == "probe_failed"


def test_info_human_probe_failure_exits_nonzero(runner, monkeypatch, clip):
    _install_probe(monkeypatch, error="probe_failed")
    result = runner.invoke(cli, ["video", "info", str(clip)])
    assert result.exit_code == 1
    assert "probe_failed" in result.output


@pytest.fixture
def ffmpeg_ready(monkeypatch):
    """Fake the runtime layer: record argv, fail on 'bad' inputs, else succeed."""
    calls = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        if any("bad" in str(part) for part in args):
            return 1, "boom"
        with open(args[-1], "wb") as handle:
            handle.write(b"encoded-output")
        return 0, ""

    _install_probe(monkeypatch)
    monkeypatch.setattr("pixshift.ops.video.run_ffmpeg", fake_run)
    return calls


def _argv_value(argv, flag):
    return argv[argv.index(flag) + 1]


SUBCOMMANDS = ["info", "convert", "compress", "trim", "thumbnail", "extract-audio", "gif"]


@pytest.mark.parametrize("subcommand", SUBCOMMANDS)
def test_every_subcommand_reports_ffmpeg_missing_json(runner, monkeypatch, clip, subcommand):
    monkeypatch.setattr("pixshift.ops.video.FFMPEG_AVAILABLE", False)
    result = runner.invoke(cli, ["video", subcommand, str(clip), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"] == "ffmpeg_missing"
    assert payload["command"] == f"video.{subcommand}"


@pytest.mark.parametrize("subcommand", SUBCOMMANDS)
def test_every_subcommand_reports_ffmpeg_missing_human(runner, monkeypatch, clip, subcommand):
    monkeypatch.setattr("pixshift.ops.video.FFMPEG_AVAILABLE", False)
    result = runner.invoke(cli, ["video", subcommand, str(clip)])
    assert result.exit_code == 1
    assert "ffmpeg" in result.output


def test_convert_batch_json_success(runner, ffmpeg_ready, tmp_path):
    for name in ("a.mp4", "b.mp4"):
        (tmp_path / name).write_bytes(b"v")
    result = runner.invoke(cli, ["video", "convert", str(tmp_path), "-t", "webm", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["total"] == 2
    assert payload["succeeded"] == 2
    outputs = {entry["output"].rsplit("/", 1)[-1] for entry in payload["results"]}
    assert outputs == {"a.webm", "b.webm"}
    assert (tmp_path / "a.webm").read_bytes() == b"encoded-output"


def test_convert_uses_requested_codec(runner, ffmpeg_ready, clip):
    result = runner.invoke(
        cli, ["video", "convert", str(clip), "-t", "mkv", "--codec", "h265", "--json"]
    )
    assert result.exit_code == 0
    assert any("libx265" in call for call in ffmpeg_ready)


def test_convert_skips_existing_output(runner, ffmpeg_ready, clip, tmp_path):
    (tmp_path / "clip.webm").write_bytes(b"already here")
    result = runner.invoke(cli, ["video", "convert", str(clip), "-t", "webm", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["skipped_existing"] == 1
    assert payload["succeeded"] == 0
    assert (tmp_path / "clip.webm").read_bytes() == b"already here"


def test_convert_failure_sets_exit_and_detail(runner, ffmpeg_ready, tmp_path):
    (tmp_path / "bad.mp4").write_bytes(b"v")
    (tmp_path / "good.mp4").write_bytes(b"v")
    result = runner.invoke(cli, ["video", "convert", str(tmp_path), "-t", "webm", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["failed"] == 1
    assert payload["succeeded"] == 1
    by_input = {entry["input"].rsplit("/", 1)[-1]: entry for entry in payload["results"]}
    assert by_input["bad.mp4"]["error"] == "ffmpeg_failed"


def test_convert_human_output_lists_states(runner, ffmpeg_ready, tmp_path):
    (tmp_path / "bad.mp4").write_bytes(b"v")
    (tmp_path / "good.mp4").write_bytes(b"v")
    (tmp_path / "kept.mp4").write_bytes(b"v")
    (tmp_path / "kept.webm").write_bytes(b"old")
    result = runner.invoke(cli, ["video", "convert", str(tmp_path), "-t", "webm"])
    assert result.exit_code == 1
    assert "完成" in result.output
    assert "跳过" in result.output
    assert "boom" in result.output


def test_convert_into_output_directory(runner, ffmpeg_ready, clip, tmp_path):
    outdir = tmp_path / "out"
    result = runner.invoke(
        cli, ["video", "convert", str(clip), "-t", "webm", "-o", str(outdir), "--json"]
    )
    assert result.exit_code == 0
    assert (outdir / "clip.webm").is_file()


def test_compress_json_names_and_crf_override(runner, ffmpeg_ready, clip, tmp_path):
    result = runner.invoke(cli, ["video", "compress", str(clip), "--crf", "30", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["results"][0]["output"].endswith("clip_compressed.mp4")
    assert (tmp_path / "clip_compressed.mp4").is_file()
    assert _argv_value(ffmpeg_ready[0], "-crf") == "30"


def test_compress_vp9_targets_webm(runner, ffmpeg_ready, clip):
    result = runner.invoke(cli, ["video", "compress", str(clip), "--codec", "vp9", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["results"][0]["output"].endswith("clip_compressed.webm")
    assert any("libvpx-vp9" in call for call in ffmpeg_ready)


def test_trim_rejects_conflicting_bounds(runner, ffmpeg_ready, clip):
    result = runner.invoke(
        cli, ["video", "trim", str(clip), "--end", "5", "--duration", "5", "--json"]
    )
    assert result.exit_code == 1
    assert json.loads(result.output)["error"] == "conflicting_options"

    human = runner.invoke(cli, ["video", "trim", str(clip), "--end", "5", "--duration", "5"])
    assert human.exit_code == 1


def test_trim_rejects_bad_timecode(runner, ffmpeg_ready, clip):
    result = runner.invoke(cli, ["video", "trim", str(clip), "--start", "abc", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error"] == "invalid_timecode"


def test_trim_stream_copies_by_default(runner, ffmpeg_ready, clip, tmp_path):
    result = runner.invoke(
        cli, ["video", "trim", str(clip), "--start", "1", "--duration", "2", "--json"]
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["output"].endswith("clip_clip.mp4")
    argv = ffmpeg_ready[0]
    assert _argv_value(argv, "-ss") == "1.000"
    assert _argv_value(argv, "-t") == "2.000"
    assert "copy" in argv


def test_trim_reencode_and_custom_output(runner, ffmpeg_ready, clip, tmp_path):
    target = tmp_path / "cut.mp4"
    result = runner.invoke(
        cli,
        [
            "video",
            "trim",
            str(clip),
            "--start",
            "0:01",
            "--end",
            "0:03",
            "--reencode",
            "-o",
            str(target),
            "--json",
        ],
    )
    assert result.exit_code == 0
    assert target.is_file()
    argv = ffmpeg_ready[0]
    assert "libx264" in argv
    assert _argv_value(argv, "-to") == "3.000"


def test_trim_failure_human_exits_nonzero(runner, ffmpeg_ready, tmp_path):
    source = tmp_path / "bad.mp4"
    source.write_bytes(b"v")
    result = runner.invoke(cli, ["video", "trim", str(source), "--start", "1"])
    assert result.exit_code == 1
    assert "失败" in result.output


def test_thumbnail_resolves_percent_against_duration(runner, ffmpeg_ready, clip, tmp_path):
    result = runner.invoke(cli, ["video", "thumbnail", str(clip), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["results"][0]["output"].endswith("clip_thumb.jpg")
    # Default --at 25% of the fake 100s probe duration.
    assert _argv_value(ffmpeg_ready[0], "-ss") == "25.000"


def test_thumbnail_timecode_and_format(runner, ffmpeg_ready, clip, tmp_path):
    result = runner.invoke(
        cli, ["video", "thumbnail", str(clip), "--at", "0:10", "-t", "png", "--json"]
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["results"][0]["output"].endswith("clip_thumb.png")
    assert _argv_value(ffmpeg_ready[0], "-ss") == "10.000"


def test_thumbnail_invalid_at_is_per_file_error(runner, ffmpeg_ready, clip):
    result = runner.invoke(cli, ["video", "thumbnail", str(clip), "--at", "150%", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["failed"] == 1
    assert payload["results"][0]["error"] == "invalid_thumbnail_at"


def test_extract_audio_defaults_to_mp3(runner, ffmpeg_ready, clip, tmp_path):
    result = runner.invoke(cli, ["video", "extract-audio", str(clip), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["results"][0]["output"].endswith("clip.mp3")
    argv = ffmpeg_ready[0]
    assert "-vn" in argv
    assert "libmp3lame" in argv
    assert _argv_value(argv, "-b:a") == "192k"


def test_extract_audio_flac_has_no_bitrate(runner, ffmpeg_ready, clip):
    result = runner.invoke(cli, ["video", "extract-audio", str(clip), "-t", "flac", "--json"])
    assert result.exit_code == 0
    argv = ffmpeg_ready[0]
    assert "flac" in argv
    assert "-b:a" not in argv


def test_gif_builds_palette_graph(runner, ffmpeg_ready, clip, tmp_path):
    result = runner.invoke(
        cli,
        ["video", "gif", str(clip), "--fps", "15", "--width", "320", "--duration", "2", "--json"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["output"].endswith("clip.gif")
    graph = _argv_value(ffmpeg_ready[0], "-filter_complex")
    assert "fps=15" in graph
    assert "scale=320" in graph
    assert "palettegen" in graph


def test_gif_rejects_bad_timecode(runner, ffmpeg_ready, clip):
    result = runner.invoke(cli, ["video", "gif", str(clip), "--start", "x:y", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error"] == "invalid_timecode"


def test_gif_human_success(runner, ffmpeg_ready, clip):
    result = runner.invoke(cli, ["video", "gif", str(clip)])
    assert result.exit_code == 0
    assert "完成" in result.output
