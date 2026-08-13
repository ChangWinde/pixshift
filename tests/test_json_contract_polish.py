"""Regression tests for the schema 1.1 polish: previews, bytes, estimate keys."""

import json

import pytest
from click.testing import CliRunner
from PIL import Image

from pixshift.cli import cli
from pixshift.video_engine import VideoInfo


@pytest.fixture
def runner():
    return CliRunner()


def test_dry_run_preview_lists_every_task(runner, tmp_path):
    for index in range(55):
        Image.new("RGB", (8, 8), "navy").save(str(tmp_path / f"img_{index:03d}.png"))
    result = runner.invoke(cli, ["resize", str(tmp_path), "--percent", "50", "--dry-run", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["total"] == 55
    assert len(payload["preview"]) == 55
    assert set(payload["preview"][0]) == {"input", "output"}


def test_strip_dry_run_preview_uses_input_key(runner, tmp_path):
    source = tmp_path / "img.png"
    Image.new("RGB", (8, 8), "navy").save(str(source))
    result = runner.invoke(cli, ["strip", str(source), "--dry-run", "--json"])
    assert result.exit_code == 0
    entry = json.loads(result.output)["preview"][0]
    assert entry["input"] == str(source)
    assert {"has_exif", "has_gps", "output", "action"} <= set(entry)


def test_manifest_and_hash_report_size_bytes(runner, tmp_path):
    source = tmp_path / "img.png"
    Image.new("RGB", (8, 8), "navy").save(str(source))
    for command in (["manifest", str(source), "--json"], ["hash", str(source), "--json"]):
        result = runner.invoke(cli, command)
        assert result.exit_code == 0
        entry = json.loads(result.output)["files"][0]
        assert entry["size_bytes"] == source.stat().st_size
        assert "bytes" not in entry


def test_image_estimates_carry_stable_format_and_label(runner, tmp_path):
    source = tmp_path / "photo.png"
    Image.new("RGB", (64, 64), "salmon").save(str(source))
    result = runner.invoke(cli, ["optimize", str(source), "--json"])
    assert result.exit_code == 0
    estimates = json.loads(result.output)["results"][0]["estimates"]
    assert estimates
    for estimate in estimates:
        assert estimate["format"] in {"jpg", "png", "webp", "avif"}
        assert estimate["label"]


def test_video_estimates_carry_codec_key_and_label(runner, monkeypatch, tmp_path):
    def fake_probe(path):
        width, height, fps = 1920, 1080, 30.0
        return VideoInfo(
            path=path,
            duration_sec=60.0,
            width=width,
            height=height,
            video_codec="h264",
            audio_codec="aac",
            fps=fps,
            bit_rate=int(0.30 * width * height * fps),
            container="mp4",
            stream_count=2,
            size_bytes=100_000_000,
        )

    monkeypatch.setattr("pixshift.ops.video.FFMPEG_AVAILABLE", True)
    monkeypatch.setattr("pixshift.ops.video.probe", fake_probe)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"fake video bytes")

    result = runner.invoke(cli, ["optimize", str(clip), "--json"])
    assert result.exit_code == 0
    estimate = json.loads(result.output)["results"][0]["estimates"][0]
    assert estimate["format"] == "h264"
    assert "web" in estimate["label"]
