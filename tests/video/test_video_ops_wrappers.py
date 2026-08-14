"""Tests for pixshift.ops.video: atomic orchestration around the argv builders."""

import pytest

from pixshift.ops import video as video_ops
from pixshift.video_engine import FFmpegNotAvailableError, VideoInfo


def _fake_run_success(args, **kwargs):
    # Builders always place the (temporary) destination path last.
    with open(args[-1], "wb") as handle:
        handle.write(b"encoded-output")
    return 0, ""


def _fake_run_failure(args, **kwargs):
    return 1, "encoder exploded"


def _fake_run_missing(args, **kwargs):
    raise FFmpegNotAvailableError("ffmpeg missing")


@pytest.fixture
def clip(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fake video bytes")
    return source


def test_available_reflects_engine_flag(monkeypatch):
    monkeypatch.setattr(video_ops, "FFMPEG_AVAILABLE", True)
    assert video_ops.available() is True
    monkeypatch.setattr(video_ops, "FFMPEG_AVAILABLE", False)
    assert video_ops.available() is False


def test_info_delegates_to_probe(monkeypatch):
    sentinel = VideoInfo(path="x.mp4", duration_sec=1.5)
    monkeypatch.setattr(video_ops, "probe", lambda path: sentinel)
    assert video_ops.info("x.mp4") is sentinel


@pytest.mark.parametrize(
    "operation,destination,kwargs",
    [
        ("convert_one", "out.webm", {"container": "webm"}),
        ("compress_one", "out_compressed.mp4", {"preset": "web", "codec": "h264"}),
        ("trim_one", "out_clip.mp4", {"start": 0.0, "duration": 2.0}),
        ("thumbnail_one", "out_thumb.jpg", {"at_seconds": 1.0}),
        ("extract_audio_one", "out.mp3", {"audio_ext": "mp3"}),
        ("gif_one", "out.gif", {}),
    ],
)
def test_each_operation_publishes_atomically(
    monkeypatch, clip, tmp_path, operation, destination, kwargs
):
    monkeypatch.setattr(video_ops, "run_ffmpeg", _fake_run_success)
    dst = tmp_path / destination
    result = getattr(video_ops, operation)(str(clip), str(dst), **kwargs)
    assert result.success is True
    assert result.error == ""
    assert dst.read_bytes() == b"encoded-output"
    assert result.input_bytes == clip.stat().st_size
    assert result.output_bytes == dst.stat().st_size


def test_failed_encode_discards_temp_and_reports(monkeypatch, clip, tmp_path):
    monkeypatch.setattr(video_ops, "run_ffmpeg", _fake_run_failure)
    dst = tmp_path / "out.webm"
    result = video_ops.convert_one(str(clip), str(dst), container="webm")
    assert result.success is False
    assert result.error == "ffmpeg_failed"
    assert result.detail == "encoder exploded"
    assert not dst.exists()
    assert not list(tmp_path.glob(".*tmp*"))


def test_missing_ffmpeg_is_a_stable_error(monkeypatch, clip, tmp_path):
    monkeypatch.setattr(video_ops, "run_ffmpeg", _fake_run_missing)
    result = video_ops.convert_one(str(clip), str(tmp_path / "o.webm"), container="webm")
    assert result.success is False
    assert result.error == "ffmpeg_missing"


def test_missing_input_short_circuits(monkeypatch, tmp_path):
    monkeypatch.setattr(video_ops, "run_ffmpeg", _fake_run_success)
    result = video_ops.convert_one(
        str(tmp_path / "absent.mp4"), str(tmp_path / "o.webm"), container="webm"
    )
    assert result.success is False
    assert result.error == "input_not_found"


def test_existing_output_skips_unless_overwrite(monkeypatch, clip, tmp_path):
    monkeypatch.setattr(video_ops, "run_ffmpeg", _fake_run_success)
    dst = tmp_path / "kept.webm"
    dst.write_bytes(b"already here")
    result = video_ops.convert_one(str(clip), str(dst), container="webm")
    assert result.success is False
    assert result.error == "output_exists"
    assert dst.read_bytes() == b"already here"

    overwritten = video_ops.convert_one(str(clip), str(dst), container="webm", overwrite=True)
    assert overwritten.success is True
    assert dst.read_bytes() == b"encoded-output"


def test_silent_encoder_failure_is_a_stable_error(monkeypatch, clip, tmp_path):
    def fake_run_no_output(args, **kwargs):
        # Exit 0 without writing the planned output: the ffmpeg failure mode
        # ADR-0005 warns about. It must become a stable per-file error.
        return 0, ""

    monkeypatch.setattr(video_ops, "run_ffmpeg", fake_run_no_output)
    dst = tmp_path / "o.webm"
    result = video_ops.convert_one(str(clip), str(dst), container="webm")
    assert result.success is False
    assert result.error == "output_not_created"
    assert result.detail != ""
    assert not dst.exists()


def test_empty_encoder_output_does_not_replace_an_existing_file(monkeypatch, clip, tmp_path):
    def fake_run_empty_output(args, **kwargs):
        open(args[-1], "wb").close()
        return 0, ""

    monkeypatch.setattr(video_ops, "run_ffmpeg", fake_run_empty_output)
    dst = tmp_path / "o.webm"
    dst.write_bytes(b"keep me")

    result = video_ops.convert_one(str(clip), str(dst), container="webm", overwrite=True)

    assert result.success is False
    assert result.error == "output_not_created"
    assert dst.read_bytes() == b"keep me"


def test_concat_direct_api_rejects_an_input_as_aggregate_output(monkeypatch, clip, tmp_path):
    second = tmp_path / "second.mp4"
    second.write_bytes(b"second clip")
    original = clip.read_bytes()
    monkeypatch.setattr(video_ops, "probe", lambda path: pytest.fail("must reject before probe"))

    result = video_ops.concat_videos([str(clip), str(second)], str(clip), overwrite=True)

    assert result.success is False
    assert result.error == "output_collision"
    assert clip.read_bytes() == original


@pytest.mark.parametrize(
    "operation,kwargs,expected_error",
    [
        ("trim_one", {"start": 5.0, "end": 3.0}, "trim_end_must_exceed_start"),
        ("gif_one", {"fps": 0}, "gif_fps_out_of_range"),
        ("extract_audio_one", {"audio_ext": "xyz"}, "unsupported_audio_format:xyz"),
    ],
)
def test_builder_validation_becomes_stable_error(
    monkeypatch, clip, tmp_path, operation, kwargs, expected_error
):
    monkeypatch.setattr(video_ops, "run_ffmpeg", _fake_run_success)
    result = getattr(video_ops, operation)(str(clip), str(tmp_path / "out.bin"), **kwargs)
    assert result.success is False
    assert result.error == expected_error
