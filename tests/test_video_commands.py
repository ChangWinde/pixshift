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
