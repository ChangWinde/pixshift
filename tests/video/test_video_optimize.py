"""Tests for the video pillar's optimize/apply loop (probe faked; no ffmpeg)."""

import json
from pathlib import Path

import jsonschema
import pytest
from click.testing import CliRunner
from PIL import Image

from pixshift.cli import cli
from pixshift.video_engine import (
    VideoInfo,
    analyze_video_info,
)

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "schemas" / "v1"


def _validate(payload, schema_name):
    jsonschema.validate(payload, json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8")))


def _info(
    *,
    path="/media/clip.mp4",
    codec="h264",
    bpp=None,
    bit_rate=None,
    width=1920,
    height=1080,
    fps=30.0,
    duration=60.0,
    audio="aac",
    size_bytes=100_000_000,
):
    pixel_rate = width * height * fps
    if bit_rate is None:
        bit_rate = int(bpp * pixel_rate) if bpp is not None else 0
    return VideoInfo(
        path=path,
        duration_sec=duration,
        width=width,
        height=height,
        video_codec=codec,
        audio_codec=audio,
        fps=fps,
        bit_rate=bit_rate,
        container="",
        stream_count=2,
        size_bytes=size_bytes,
    )


# ------------------------------------------------------------------
# Pure analysis
# ------------------------------------------------------------------


def test_legacy_codec_in_legacy_container_converts():
    result = analyze_video_info(_info(path="/media/old.avi", codec="mpeg4", bpp=0.4))
    assert result.action == "video.convert"
    assert result.plan == {"command": "video.convert", "arguments": {"to": "mp4", "codec": "h264"}}
    assert result.estimated_bytes > 0
    assert "陈旧编码" in result.reason


def test_legacy_codec_in_modern_container_compresses_to_avoid_collision():
    result = analyze_video_info(_info(path="/media/old.mp4", codec="mpeg4", bpp=0.4))
    assert result.action == "video.compress"
    assert result.plan["arguments"] == {"preset": "web", "codec": "h264"}


def test_vp8_modernises_within_the_webm_family():
    result = analyze_video_info(_info(path="/media/clip.webm", codec="vp8", bpp=0.3))
    assert result.plan["arguments"]["codec"] == "vp9"


def test_wasteful_h264_gets_a_same_family_compress():
    result = analyze_video_info(_info(codec="h264", bpp=0.30))
    assert result.action == "video.compress"
    assert result.plan["arguments"] == {"preset": "web", "codec": "h264"}
    assert result.estimated_bytes > 0
    assert "重压预计可省约" in result.reason


def test_wasteful_hevc_stays_in_family():
    result = analyze_video_info(_info(codec="hevc", bpp=0.30))
    assert result.plan["arguments"]["codec"] == "h265"


def test_efficient_h264_is_kept():
    result = analyze_video_info(_info(codec="h264", bpp=0.08))
    assert result.action == "keep"
    assert result.plan == {"command": "keep", "arguments": {}}
    assert result.estimated_bytes == 0


def test_missing_probe_signal_is_kept_conservatively():
    result = analyze_video_info(_info(codec="h264", bit_rate=0))
    assert result.action == "keep"
    assert "探测信号不足" in result.reason


def test_fat_intermediate_codec_converts_to_h264():
    result = analyze_video_info(_info(path="/media/master.mov", codec="prores", bpp=1.5))
    assert result.action == "video.convert"
    assert result.plan["arguments"] == {"to": "mp4", "codec": "h264"}


def test_unknown_lean_codec_is_kept():
    result = analyze_video_info(_info(codec="mysterycodec", bpp=0.05))
    assert result.action == "keep"


def test_estimate_accounts_for_audio():
    with_audio = analyze_video_info(_info(codec="h264", bpp=0.30, audio="aac"))
    without_audio = analyze_video_info(_info(codec="h264", bpp=0.30, audio=""))
    assert with_audio.estimated_bytes > without_audio.estimated_bytes


def test_analysis_reports_bits_per_pixel():
    result = analyze_video_info(_info(codec="h264", bpp=0.30))
    assert result.bits_per_pixel == pytest.approx(0.30, abs=0.01)
    assert result.video_codec == "h264"
    assert result.input_bytes == 100_000_000


# ------------------------------------------------------------------
# optimize CLI
# ------------------------------------------------------------------


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def clip(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fake video bytes")
    return source


def _install_probe(monkeypatch, *, bpp=0.30, codec="h264"):
    def fake_probe(path):
        width, height, fps = 1920, 1080, 30.0
        return VideoInfo(
            path=path,
            duration_sec=60.0,
            width=width,
            height=height,
            video_codec=codec,
            audio_codec="aac",
            fps=fps,
            bit_rate=int(bpp * width * height * fps),
            container="mp4",
            stream_count=2,
            size_bytes=100_000_000,
        )

    monkeypatch.setattr("pixshift.ops.video.FFMPEG_AVAILABLE", True)
    monkeypatch.setattr("pixshift.ops.video.probe", fake_probe)


def test_optimize_json_recommends_video_compress(runner, monkeypatch, clip):
    _install_probe(monkeypatch, bpp=0.30)
    result = runner.invoke(cli, ["optimize", str(clip), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["total"] == 1
    entry = payload["results"][0]
    assert entry["media_type"] == "video"
    assert entry["plan"] == {
        "command": "video.compress",
        "arguments": {"preset": "web", "codec": "h264"},
    }
    assert entry["estimates"][0]["estimated_bytes"] > 0
    assert entry["analysis"]["video_codec"] == "h264"
    _validate(payload, "optimize.json")
    _validate(payload, "envelope.json")


def test_optimize_json_keep_for_efficient_video(runner, monkeypatch, clip):
    _install_probe(monkeypatch, bpp=0.08)
    result = runner.invoke(cli, ["optimize", str(clip), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["results"][0]["plan"]["command"] == "keep"
    _validate(payload, "optimize.json")


def test_optimize_mixed_directory_analyses_both_pillars(runner, monkeypatch, tmp_path):
    _install_probe(monkeypatch, bpp=0.30)
    Image.new("RGB", (64, 64), "red").save(tmp_path / "photo.png")
    (tmp_path / "clip.mp4").write_bytes(b"fake video bytes")
    result = runner.invoke(cli, ["optimize", str(tmp_path), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["total"] == 2
    kinds = {entry["media_type"] for entry in payload["results"]}
    assert kinds == {"image", "video"}
    _validate(payload, "optimize.json")


def test_optimize_video_without_ffmpeg_is_a_stable_error(runner, monkeypatch, clip):
    monkeypatch.setattr("pixshift.ops.video.FFMPEG_AVAILABLE", False)
    result = runner.invoke(cli, ["optimize", str(clip), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    entry = payload["results"][0]
    assert entry["error"] == "ffmpeg_missing"
    assert entry["plan"] == {}
    _validate(payload, "optimize.json")


def test_optimize_human_table_lists_video_row(runner, monkeypatch, clip):
    _install_probe(monkeypatch, bpp=0.30)
    result = runner.invoke(cli, ["optimize", str(clip)])
    assert result.exit_code == 0
    assert "video" in result.output
    assert "video compress" in result.output


def test_optimize_empty_inputs_still_report_no_files(runner, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = runner.invoke(cli, ["optimize", str(empty), "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["message"] == "no_files"


# ------------------------------------------------------------------
# apply
# ------------------------------------------------------------------


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


def _plan_doc(steps):
    return json.dumps(steps)


def test_apply_video_compress_step(runner, ffmpeg_ready, clip, tmp_path):
    plan = _plan_doc(
        [
            {
                "input": str(clip),
                "command": "video.compress",
                "arguments": {"preset": "web", "codec": "h264", "crf": 30},
            }
        ]
    )
    result = runner.invoke(cli, ["apply", "--plan", "-", "--json"], input=plan)
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["applied"] == 1
    step = payload["steps"][0]
    assert step["output"].endswith("clip_compressed.mp4")
    assert (tmp_path / "clip_compressed.mp4").read_bytes() == b"encoded-output"
    argv = ffmpeg_ready[0]
    assert argv[argv.index("-crf") + 1] == "30"
    _validate(payload, "apply.json")
    _validate(payload, "envelope.json")


def test_apply_video_convert_step(runner, ffmpeg_ready, clip, tmp_path):
    plan = _plan_doc(
        [{"input": str(clip), "command": "video.convert", "arguments": {"to": "webm"}}]
    )
    result = runner.invoke(cli, ["apply", "--plan", "-", "--json"], input=plan)
    assert result.exit_code == 0
    assert (tmp_path / "clip.webm").is_file()
    assert any("libvpx-vp9" in call for call in ffmpeg_ready)


def test_apply_keep_step_is_an_explicit_noop(runner, clip):
    plan = _plan_doc([{"input": str(clip), "command": "keep", "arguments": {}}])
    result = runner.invoke(cli, ["apply", "--plan", "-", "--json"], input=plan)
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["skipped"] == 1
    assert payload["steps"][0]["detail"] == "plan_keep"
    assert payload["steps"][0]["output"] == ""


def test_apply_video_dry_run_works_without_ffmpeg(runner, monkeypatch, clip, tmp_path):
    monkeypatch.setattr("pixshift.ops.video.FFMPEG_AVAILABLE", False)
    plan = _plan_doc(
        [{"input": str(clip), "command": "video.compress", "arguments": {"codec": "h264"}}]
    )
    result = runner.invoke(cli, ["apply", "--plan", "-", "--dry-run", "--json"], input=plan)
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["steps"][0]["output"].endswith("clip_compressed.mp4")
    assert not (tmp_path / "clip_compressed.mp4").exists()


def test_apply_video_without_ffmpeg_fails_stably(runner, monkeypatch, clip):
    monkeypatch.setattr("pixshift.ops.video.FFMPEG_AVAILABLE", False)
    plan = _plan_doc([{"input": str(clip), "command": "video.compress", "arguments": {}}])
    result = runner.invoke(cli, ["apply", "--plan", "-", "--json"], input=plan)
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["steps"][0]["error"] == "ffmpeg_missing"


@pytest.mark.parametrize(
    "arguments,expected",
    [
        ({"to": "avi"}, "unsupported_target_container:avi"),
        ({"to": "mp4", "codec": "nope"}, "unsupported_video_codec:nope"),
    ],
)
def test_apply_video_convert_validates_vocabulary(runner, clip, arguments, expected):
    plan = _plan_doc([{"input": str(clip), "command": "video.convert", "arguments": arguments}])
    result = runner.invoke(cli, ["apply", "--plan", "-", "--dry-run", "--json"], input=plan)
    assert result.exit_code == 2
    assert json.loads(result.output)["steps"][0]["error"] == expected


def test_apply_video_compress_validates_preset(runner, clip):
    plan = _plan_doc(
        [{"input": str(clip), "command": "video.compress", "arguments": {"preset": "nope"}}]
    )
    result = runner.invoke(cli, ["apply", "--plan", "-", "--dry-run", "--json"], input=plan)
    assert result.exit_code == 2
    assert json.loads(result.output)["steps"][0]["error"] == "unsupported_video_preset:nope"


def test_apply_video_detects_output_collisions(runner, clip):
    step = {"input": str(clip), "command": "video.compress", "arguments": {}}
    plan = _plan_doc([step, dict(step)])
    result = runner.invoke(cli, ["apply", "--plan", "-", "--dry-run", "--json"], input=plan)
    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["steps"][0]["ok"] is True
    assert payload["steps"][1]["error"] == "output_collision"


def test_optimize_payload_feeds_apply_directly(runner, monkeypatch, clip, tmp_path):
    _install_probe(monkeypatch, bpp=0.30)
    optimized = runner.invoke(cli, ["optimize", str(clip), "--json"])
    assert optimized.exit_code == 0

    result = runner.invoke(
        cli, ["apply", "--plan", "-", "--dry-run", "--json"], input=optimized.output
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["total"] == 1
    step = payload["steps"][0]
    assert step["plan_command"] == "video.compress"
    assert step["ok"] is True
    assert step["output"].endswith("clip_compressed.mp4")


def test_optimize_keep_verdict_applies_as_skip(runner, monkeypatch, clip):
    _install_probe(monkeypatch, bpp=0.08)
    optimized = runner.invoke(cli, ["optimize", str(clip), "--json"])
    assert optimized.exit_code == 0

    result = runner.invoke(cli, ["apply", "--plan", "-", "--json"], input=optimized.output)
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["skipped"] == 1
    assert payload["steps"][0]["detail"] == "plan_keep"
