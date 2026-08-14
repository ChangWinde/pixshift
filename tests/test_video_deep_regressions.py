"""Regression tests for video stream selection, publication, and process cleanup."""

from __future__ import annotations

import io
import json
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest

from pixshift import video_engine
from pixshift.ops import video as video_ops
from pixshift.video_engine import (
    VideoInfo,
    build_concat_segment_args,
    build_convert_args,
    probe,
    run_ffmpeg,
)


def test_concat_segment_pads_short_audio_before_using_shortest(tmp_path):
    args = build_concat_segment_args(
        str(tmp_path / "source.mp4"),
        str(tmp_path / "segment.mp4"),
        width=1280,
        height=720,
        fps=30,
        source_has_audio=True,
        include_audio=True,
    )

    assert args[args.index("-af") + 1] == "apad"
    assert "-shortest" in args


def _commit_race(tmp_path, destination):
    @contextmanager
    def racing_output(_path, *, overwrite):
        temporary = tmp_path / "encoded.tmp"
        yield str(temporary)
        destination.write_bytes(b"concurrent winner")
        raise FileExistsError("output_exists")

    return racing_output


def test_video_convert_commit_race_reports_output_exists(monkeypatch, tmp_path):
    source = tmp_path / "source.mp4"
    output = tmp_path / "output.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(video_ops, "atomic_output_path", _commit_race(tmp_path, output))

    def fake_run(args, **kwargs):
        Path(args[-1]).write_bytes(b"encoded")
        return 0, ""

    monkeypatch.setattr(video_ops, "run_ffmpeg", fake_run)

    result = video_ops.convert_one(str(source), str(output), container="mp4")

    assert result.error == "output_exists"
    assert output.read_bytes() == b"concurrent winner"


def test_video_target_copy_commit_race_reports_output_exists(monkeypatch, tmp_path):
    source = tmp_path / "source.mp4"
    output = tmp_path / "output.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(video_ops, "atomic_output_path", _commit_race(tmp_path, output))

    result = video_ops.compress_to_target_one(str(source), str(output), target_bytes=1000)

    assert result.error == "output_exists"
    assert output.read_bytes() == b"concurrent winner"


def test_video_concat_commit_race_reports_output_exists(monkeypatch, tmp_path):
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    output = tmp_path / "output.mp4"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    info = VideoInfo(
        path="",
        video_codec="h264",
        video_profile="High",
        video_level=41,
        pixel_format="yuv420p",
        frame_rate="30/1",
        video_time_base="1/15360",
        sample_aspect_ratio="1:1",
        field_order="progressive",
        video_extradata_hash="SHA256:same",
        width=1280,
        height=720,
    )
    monkeypatch.setattr(
        video_ops, "probe", lambda path: VideoInfo(**{**info.__dict__, "path": path})
    )
    monkeypatch.setattr(video_ops, "atomic_output_path", _commit_race(tmp_path, output))

    def fake_run(args, **kwargs):
        Path(args[-1]).write_bytes(b"encoded")
        return 0, ""

    monkeypatch.setattr(video_ops, "run_ffmpeg", fake_run)

    result = video_ops.concat_videos([str(first), str(second)], str(output))

    assert result.error == "output_exists"
    assert output.read_bytes() == b"concurrent winner"


def test_probe_ignores_attached_picture_before_real_video(monkeypatch, tmp_path):
    source = tmp_path / "album.mp4"
    source.write_bytes(b"video")
    payload = {
        "format": {"duration": "2", "bit_rate": "1000", "format_name": "mov,mp4"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "mjpeg",
                "width": 600,
                "height": 600,
                "avg_frame_rate": "0/0",
                "disposition": {"attached_pic": 1},
            },
            {
                "codec_type": "video",
                "codec_name": "h264",
                "profile": "High",
                "pix_fmt": "yuv420p",
                "level": 41,
                "sample_aspect_ratio": "1:1",
                "field_order": "progressive",
                "extradata_hash": "SHA256:abc",
                "color_range": "tv",
                "color_space": "bt709",
                "color_primaries": "bt709",
                "color_transfer": "bt709",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30/1",
                "time_base": "1/15360",
                "disposition": {"attached_pic": 0},
            },
        ],
    }
    monkeypatch.setattr(video_engine, "FFMPEG_AVAILABLE", True)
    monkeypatch.setattr(
        video_engine.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=json.dumps(payload), stderr=""
        ),
    )

    info = probe(str(source))

    assert (info.video_codec, info.width, info.height, info.fps) == (
        "h264",
        1920,
        1080,
        30.0,
    )
    assert (info.video_profile, info.pixel_format, info.video_time_base) == (
        "High",
        "yuv420p",
        "1/15360",
    )
    assert (info.video_level, info.sample_aspect_ratio, info.field_order) == (
        41,
        "1:1",
        "progressive",
    )
    assert info.video_extradata_hash == "SHA256:abc"


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups only")
def test_run_ffmpeg_timeout_kills_the_process_group(monkeypatch):
    class HangingProcess:
        pid = 4321
        returncode = None
        stderr = io.StringIO("line\n")

        def __init__(self):
            self.running = True
            self.kill_called = False

        def wait(self, timeout=None):
            if self.running:
                raise subprocess.TimeoutExpired("ffmpeg", timeout)
            self.returncode = -9
            return self.returncode

        def kill(self):
            self.kill_called = True
            self.running = False

    process = HangingProcess()
    popen_options = {}
    killed_groups = []

    def fake_popen(*args, **kwargs):
        popen_options.update(kwargs)
        return process

    def fake_killpg(group, sig):
        killed_groups.append((group, sig))
        process.running = False

    monkeypatch.setattr(video_engine, "FFMPEG_AVAILABLE", True)
    monkeypatch.setattr(video_engine.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(video_engine.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(video_engine.os, "killpg", fake_killpg)

    assert run_ffmpeg(["-i", "in.mp4", "out.mp4"], timeout=0.01) == (
        124,
        "ffmpeg_timeout",
    )
    assert popen_options["start_new_session"] is True
    assert killed_groups == [(process.pid, video_engine.signal.SIGKILL)]
    assert process.kill_called is False


def test_target_size_cross_container_encodes_instead_of_copying(monkeypatch, tmp_path):
    source = tmp_path / "source.mov"
    output = tmp_path / "output.mp4"
    source.write_bytes(b"source-container-bytes")
    calls = []

    monkeypatch.setattr(
        video_ops,
        "probe",
        lambda path: VideoInfo(path=path, duration_sec=2.0, video_codec="h264"),
    )

    def fake_run(args, **kwargs):
        calls.append(list(args))
        if args[-1] != os.devnull:
            Path(args[-1]).write_bytes(b"encoded-mp4")
        return 0, ""

    monkeypatch.setattr(video_ops, "run_ffmpeg", fake_run)

    result = video_ops.compress_to_target_one(
        str(source), str(output), target_bytes=10_000, codec="h264"
    )

    assert result.success is True
    assert calls
    assert output.read_bytes() == b"encoded-mp4"
    assert output.read_bytes() != source.read_bytes()


def test_convert_rejects_codec_container_pair_before_ffmpeg():
    with pytest.raises(ValueError, match="unsupported_codec_for_container:h264:webm"):
        build_convert_args("in.mp4", "out.webm", container="webm", codec="h264")


def test_concat_copy_requires_full_stream_signature(monkeypatch, tmp_path):
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    first.write_bytes(b"a")
    second.write_bytes(b"b")

    def fake_probe(path):
        return VideoInfo(
            path=path,
            video_codec="h264",
            video_profile="High",
            pixel_format="yuv420p",
            frame_rate="30/1" if path == str(first) else "25/1",
            video_time_base="1/15360",
            width=1280,
            height=720,
            audio_codec="aac",
            audio_sample_rate=48000,
            audio_channels=2,
            audio_channel_layout="stereo",
        )

    monkeypatch.setattr(video_ops, "probe", fake_probe)
    monkeypatch.setattr(
        video_ops,
        "run_ffmpeg",
        lambda *args, **kwargs: pytest.fail("incompatible streams must not reach ffmpeg"),
    )

    result = video_ops.concat_videos([str(first), str(second)], str(tmp_path / "joined.mp4"))

    assert result.success is False
    assert result.error == "concat_requires_matching_streams"
    assert result.detail == "stream signatures differ; pass --reencode to normalise"


def test_concat_copy_rejects_sample_aspect_ratio_mismatch(monkeypatch, tmp_path):
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    first.write_bytes(b"a")
    second.write_bytes(b"b")

    def fake_probe(path):
        return VideoInfo(
            path=path,
            video_codec="h264",
            video_profile="High",
            video_level=41,
            pixel_format="yuv420p",
            frame_rate="30/1",
            video_time_base="1/15360",
            sample_aspect_ratio="1:1" if path == str(first) else "4:3",
            field_order="progressive",
            video_extradata_hash="SHA256:same",
            width=1280,
            height=720,
        )

    monkeypatch.setattr(video_ops, "probe", fake_probe)
    monkeypatch.setattr(
        video_ops,
        "run_ffmpeg",
        lambda *args, **kwargs: pytest.fail("incompatible streams must not reach ffmpeg"),
    )

    result = video_ops.concat_videos([str(first), str(second)], str(tmp_path / "joined.mp4"))

    assert result.error == "concat_requires_matching_streams"


def test_concat_reencode_normalizes_every_segment_before_join(monkeypatch, tmp_path):
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.webm"
    output = tmp_path / "joined.mp4"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    calls = []

    def fake_probe(path):
        is_first = path == str(first)
        return VideoInfo(
            path=path,
            video_codec="h264" if is_first else "vp9",
            width=640 if is_first else 320,
            height=360 if is_first else 240,
            fps=30.0 if is_first else 25.0,
            audio_codec="aac" if is_first else "",
        )

    def fake_run(args, **kwargs):
        calls.append(list(args))
        Path(args[-1]).write_bytes(b"encoded")
        return 0, ""

    monkeypatch.setattr(video_ops, "probe", fake_probe)
    monkeypatch.setattr(video_ops, "run_ffmpeg", fake_run)

    result = video_ops.concat_videos([str(first), str(second)], str(output), reencode=True)

    assert result.success is True
    assert len(calls) == 3
    assert calls[0][calls[0].index("-i") + 1] == str(first.resolve())
    assert calls[1][calls[1].index("-i") + 1] == str(second.resolve())
    assert "anullsrc=channel_layout=stereo:sample_rate=48000" in calls[1]
    assert "1:a:0" in calls[1]
    assert "copy" in calls[2]
    assert output.read_bytes() == b"encoded"
