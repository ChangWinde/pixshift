"""Tests for the video engine runtime: probe parsing, run_ffmpeg, file collection."""

import io
import json
import subprocess
from pathlib import Path

import pytest

from pixshift import video_engine
from pixshift.video_engine import (
    FFmpegNotAvailableError,
    _ffprobe_fps,
    collect_video_files,
    probe,
    run_ffmpeg,
)


def _probe_payload(**overrides):
    payload = {
        "format": {
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            "duration": "12.5",
            "bit_rate": "1200000",
        },
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30000/1001",
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def clip(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fake video bytes")
    return source


def _patch_ffprobe(monkeypatch, *, returncode=0, stdout="", raises=None):
    def fake_run(command, **kwargs):
        assert command[0] == "ffprobe"
        assert kwargs.get("stdin") is subprocess.DEVNULL
        assert kwargs.get("timeout") == video_engine.PROBE_TIMEOUT_S
        if raises is not None:
            raise raises
        return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(video_engine, "FFMPEG_AVAILABLE", True)
    monkeypatch.setattr(video_engine.subprocess, "run", fake_run)


def test_probe_parses_streams_and_format(monkeypatch, clip):
    _patch_ffprobe(monkeypatch, stdout=json.dumps(_probe_payload()))
    info = probe(str(clip))
    assert info.error == ""
    assert info.exists is True
    assert info.duration_sec == pytest.approx(12.5)
    assert info.bit_rate == 1200000
    assert (info.width, info.height) == (1920, 1080)
    assert info.video_codec == "h264"
    assert info.audio_codec == "aac"
    assert info.fps == pytest.approx(29.97, abs=0.01)
    assert info.stream_count == 2
    assert info.size_bytes == clip.stat().st_size


def test_probe_tolerates_unparsable_numbers(monkeypatch, clip):
    payload = _probe_payload()
    payload["format"] = {"format_name": "mp4", "duration": "N/A", "bit_rate": None}
    payload["streams"] = [{"codec_type": "video", "codec_name": "h264", "avg_frame_rate": "0/0"}]
    _patch_ffprobe(monkeypatch, stdout=json.dumps(payload))
    info = probe(str(clip))
    assert info.error == ""
    assert info.duration_sec == 0.0
    assert info.bit_rate == 0
    assert (info.width, info.height) == (0, 0)
    assert info.fps == 0.0
    assert info.audio_codec == ""


def test_probe_missing_input(tmp_path):
    info = probe(str(tmp_path / "absent.mp4"))
    assert info.exists is False
    assert info.error == "input_not_found"


def test_probe_requires_ffmpeg(monkeypatch, clip):
    monkeypatch.setattr(video_engine, "FFMPEG_AVAILABLE", False)
    with pytest.raises(FFmpegNotAvailableError):
        probe(str(clip))


def test_probe_failure_modes(monkeypatch, clip):
    _patch_ffprobe(monkeypatch, returncode=1)
    assert probe(str(clip)).error == "probe_failed"

    _patch_ffprobe(monkeypatch, stdout="not json at all")
    assert probe(str(clip)).error == "probe_unparsable"

    _patch_ffprobe(monkeypatch, raises=subprocess.TimeoutExpired(cmd="ffprobe", timeout=20.0))
    assert probe(str(clip)).error == "probe_timeout"


@pytest.mark.parametrize(
    "rate,expected",
    [
        ("30000/1001", 29.97),
        ("25/1", 25.0),
        ("30", 30.0),
        ("0/0", 0.0),
        ("0", 0.0),
        ("", 0.0),
        ("5/0", 0.0),
        ("abc", 0.0),
        ("a/b", 0.0),
    ],
)
def test_ffprobe_fps_parsing(rate, expected):
    assert _ffprobe_fps(rate) == pytest.approx(expected, abs=0.01)


class _FakeProcess:
    def __init__(self, stderr_text="", returncode=0, hang=False):
        self.stderr = io.StringIO(stderr_text)
        self.returncode = returncode
        self.killed = False
        self._hang = hang

    def wait(self, timeout=None):
        if self._hang and timeout is not None:
            raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=timeout)
        return self.returncode

    def kill(self):
        self.killed = True
        self._hang = False


def test_run_ffmpeg_requires_ffmpeg(monkeypatch):
    monkeypatch.setattr(video_engine, "FFMPEG_AVAILABLE", False)
    with pytest.raises(FFmpegNotAvailableError):
        run_ffmpeg(["-i", "in.mp4", "out.mp4"])


def test_run_ffmpeg_returns_code_and_stderr_tail(monkeypatch):
    commands = []
    stderr_text = "".join(f"line{i}\n" for i in range(1, 8))
    process = _FakeProcess(stderr_text=stderr_text, returncode=3)

    def fake_popen(command, **kwargs):
        commands.append(command)
        assert kwargs.get("stdin") is subprocess.DEVNULL
        return process

    monkeypatch.setattr(video_engine, "FFMPEG_AVAILABLE", True)
    monkeypatch.setattr(video_engine.subprocess, "Popen", fake_popen)
    returncode, tail = run_ffmpeg(["-i", "in.mp4", "out.mp4"])
    assert returncode == 3
    assert "line7" in tail
    assert "line1" not in tail
    command = commands[0]
    assert command[0] == "ffmpeg"
    for flag in ("-hide_banner", "-nostdin", "-y"):
        assert flag in command


def test_run_ffmpeg_kills_hung_process(monkeypatch):
    process = _FakeProcess(hang=True)
    monkeypatch.setattr(video_engine, "FFMPEG_AVAILABLE", True)
    monkeypatch.setattr(video_engine.subprocess, "Popen", lambda *a, **k: process)
    returncode, tail = run_ffmpeg(["-i", "in.mp4", "out.mp4"], timeout=0.01)
    assert returncode == 124
    assert tail == "ffmpeg_timeout"
    assert process.killed is True


def test_collect_video_files(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"a")
    (tmp_path / "b.MOV").write_bytes(b"b")
    (tmp_path / "notes.txt").write_text("not a video")
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / "c.mkv").write_bytes(b"c")

    flat = collect_video_files([str(tmp_path)])
    assert [Path(p).name for p in flat] == ["a.mp4", "b.MOV"]

    deep = collect_video_files([str(tmp_path)], recursive=True)
    assert [Path(p).name for p in deep] == ["a.mp4", "b.MOV", "c.mkv"]

    # Explicit non-video files are ignored; duplicates collapse.
    mixed = collect_video_files(
        [str(tmp_path / "notes.txt"), str(tmp_path / "a.mp4"), str(tmp_path)]
    )
    assert [Path(p).name for p in mixed] == ["a.mp4", "b.MOV"]
