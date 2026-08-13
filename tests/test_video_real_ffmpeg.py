"""Video pillar tests against a real ffmpeg (skipped when it is absent).

Everything else fakes the runtime layer; these tests exist precisely to catch
the class of bug fakes cannot: encoder wrappers rejecting flags (libx265's
two-pass handling differs from x264), stream-copy semantics, real probe
fields, and byte budgets holding on real encodes. CI installs ffmpeg so they
run on every pull request.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from pixshift.cli import cli

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH",
)


@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    """Synthesise deterministic test clips with lavfi sources."""
    base = tmp_path_factory.mktemp("clips")

    def make(name, *, duration=2.0, size="320x240", rate=24, audio=True, crf=23):
        path = base / name
        args = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={size}:rate={rate}:duration={duration}",
        ]
        if audio:
            args += [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=440:duration={duration}",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
                "-shortest",
            ]
        args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), str(path)]
        subprocess.run(args, check=True, capture_output=True)
        return path

    return {
        "main": make("main.mp4"),
        "twin": make("twin.mp4"),
        "small": make("small.mp4", size="160x120", audio=False),
        "rich": make("rich.mp4", duration=4.0, size="640x480", crf=10),
        "dir": base,
    }


def _run(args, input_text=None):
    runner = CliRunner()
    return runner.invoke(cli, args, input=input_text)


def test_info_reports_real_probe_fields(clips):
    result = _run(["video", "info", str(clips["main"]), "--json"])
    assert result.exit_code == 0, result.output
    entry = json.loads(result.output)["files"][0]
    assert entry["video_codec"] == "h264"
    assert entry["audio_codec"] == "aac"
    assert entry["width"] == 320
    assert 1.5 <= entry["duration_sec"] <= 2.6
    assert 23 <= entry["fps"] <= 25


def test_convert_transcodes_to_webm(clips, tmp_path):
    result = _run(
        ["video", "convert", str(clips["small"]), "-t", "webm", "-o", str(tmp_path), "--json"]
    )
    assert result.exit_code == 0, result.output
    produced = tmp_path / "small.webm"
    assert produced.is_file() and produced.stat().st_size > 0


def test_compress_preset_produces_playable_output(clips, tmp_path):
    result = _run(
        ["video", "compress", str(clips["rich"]), "-p", "web", "-o", str(tmp_path), "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["succeeded"] == 1
    produced = tmp_path / "rich_compressed.mp4"
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-print_format", "json", str(produced)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(probe.stdout)["format"]["format_name"].startswith("mov")


@pytest.mark.parametrize("codec", ["h264", "h265", "vp9"])
def test_target_size_two_pass_fits_real_budgets(clips, tmp_path, codec):
    source = clips["rich"]
    target = int(source.stat().st_size * 0.5)
    out_dir = tmp_path / codec
    out_dir.mkdir()
    result = _run(
        [
            "video",
            "compress",
            str(source),
            "--target-size",
            str(target),
            "--codec",
            codec,
            "-o",
            str(out_dir),
            "--json",
        ]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["succeeded"] == 1, payload
    produced = next(out_dir.iterdir())
    assert 0 < produced.stat().st_size <= target


def test_trim_stream_copy_and_reencode(clips, tmp_path):
    copy_out = tmp_path / "cut.mp4"
    result = _run(
        [
            "video",
            "trim",
            str(clips["main"]),
            "--start",
            "0.5",
            "--duration",
            "1",
            "-o",
            str(copy_out),
            "--json",
        ]
    )
    assert result.exit_code == 0, result.output
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-print_format", "json", str(copy_out)],
        capture_output=True,
        text=True,
        check=True,
    )
    duration = float(json.loads(probe.stdout)["format"]["duration"])
    assert 0.5 <= duration <= 1.8  # keyframe-aligned copy is approximate

    precise_out = tmp_path / "cut_precise.mp4"
    result = _run(
        [
            "video",
            "trim",
            str(clips["main"]),
            "--start",
            "0.5",
            "--duration",
            "1",
            "--reencode",
            "-o",
            str(precise_out),
            "--json",
        ]
    )
    assert result.exit_code == 0, result.output


def test_thumbnail_and_audio_and_gif(clips, tmp_path):
    result = _run(
        ["video", "thumbnail", str(clips["main"]), "--at", "50%", "-o", str(tmp_path), "--json"]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "main_thumb.jpg").stat().st_size > 0

    result = _run(
        ["video", "extract-audio", str(clips["main"]), "-t", "mp3", "-o", str(tmp_path), "--json"]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "main.mp3").stat().st_size > 0

    gif_out = tmp_path / "clip.gif"
    result = _run(
        [
            "video",
            "gif",
            str(clips["small"]),
            "--duration",
            "1",
            "--fps",
            "8",
            "--width",
            "120",
            "-o",
            str(gif_out),
            "--json",
        ]
    )
    assert result.exit_code == 0, result.output
    assert gif_out.stat().st_size > 0


def test_concat_stream_copy_sums_durations(clips, tmp_path):
    joined = tmp_path / "joined.mp4"
    result = _run(
        ["video", "concat", str(clips["main"]), str(clips["twin"]), "-o", str(joined), "--json"]
    )
    assert result.exit_code == 0, result.output
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-print_format", "json", str(joined)],
        capture_output=True,
        text=True,
        check=True,
    )
    duration = float(json.loads(probe.stdout)["format"]["duration"])
    assert 3.4 <= duration <= 4.6


def test_concat_rejects_mismatched_then_reencodes(clips, tmp_path):
    rejected = _run(
        [
            "video",
            "concat",
            str(clips["main"]),
            str(clips["small"]),
            "-o",
            str(tmp_path / "no.mp4"),
            "--json",
        ]
    )
    assert rejected.exit_code == 1
    assert json.loads(rejected.output)["error"] == "concat_requires_matching_streams"

    forced = _run(
        [
            "video",
            "concat",
            str(clips["main"]),
            str(clips["small"]),
            "--reencode",
            "-o",
            str(tmp_path / "yes.mp4"),
            "--json",
        ]
    )
    assert forced.exit_code == 0, forced.output
    assert (tmp_path / "yes.mp4").stat().st_size > 0


def test_optimize_to_apply_loop_on_a_real_clip(clips, tmp_path):
    optimized = _run(["optimize", str(clips["rich"]), "--json"])
    assert optimized.exit_code == 0, optimized.output
    entry = json.loads(optimized.output)["results"][0]
    assert entry["media_type"] == "video"
    assert entry["plan"]["command"] in ("video.compress", "video.convert", "keep")

    if entry["plan"]["command"] == "keep":
        pytest.skip("probe judged the clip already efficient")
    applied = _run(
        ["apply", "--plan", "-", "-o", str(tmp_path), "--json"], input_text=optimized.output
    )
    assert applied.exit_code == 0, applied.output
    step = json.loads(applied.output)["steps"][0]
    assert step["ok"] is True
    assert (tmp_path / Path(step["output"]).name).stat().st_size > 0
