"""Tests for animated-image transforms: frames, timing, loops, and plans."""

import json
from pathlib import Path

import jsonschema
import pytest
from click.testing import CliRunner
from PIL import Image, ImageSequence

from pixshift.cli import cli
from pixshift.converter import PixShiftConverter

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "schemas" / "v1"


def _validate(payload, schema_name):
    jsonschema.validate(payload, json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8")))


def _make_animated_gif(path, size=(32, 32)):
    frames = [Image.new("RGB", size, color) for color in ("red", "green", "blue")]
    frames[0].save(
        str(path),
        save_all=True,
        append_images=frames[1:],
        duration=[100, 200, 300],
        loop=2,
        disposal=2,
    )


def _make_apng(path):
    frames = [
        Image.new("RGBA", (24, 24), (255, 0, 0, 255)),
        Image.new("RGBA", (24, 24), (0, 255, 0, 128)),
    ]
    frames[0].save(str(path), save_all=True, append_images=frames[1:], duration=120, loop=1)


def _make_animated_webp(path):
    frames = [Image.new("RGB", (24, 24), color) for color in ("red", "blue")]
    frames[0].save(str(path), save_all=True, append_images=frames[1:], duration=[80, 90], loop=0)


def _frame_summary(path):
    with Image.open(path) as img:
        durations = []
        for index in range(getattr(img, "n_frames", 1)):
            img.seek(index)
            img.load()  # WebP publishes per-frame duration only after load
            durations.append(img.info.get("duration", 0))
        return {
            "frames": getattr(img, "n_frames", 1),
            "durations": durations,
            "loop": img.info.get("loop"),
        }


@pytest.fixture
def runner():
    return CliRunner()


def test_gif_to_webp_preserves_animation(runner, tmp_path):
    source = tmp_path / "anim.gif"
    _make_animated_gif(source)
    result = runner.invoke(cli, ["convert", str(source), "-t", "webp", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["success"] == 1

    summary = _frame_summary(tmp_path / "anim.webp")
    assert summary["frames"] == 3
    assert summary["durations"] == [100, 200, 300]
    assert summary["loop"] == 2


def test_apng_to_webp_keeps_frames_and_alpha(runner, tmp_path):
    source = tmp_path / "anim.png"
    _make_apng(source)
    result = runner.invoke(cli, ["convert", str(source), "-t", "webp", "--json"])
    assert result.exit_code == 0

    output = tmp_path / "anim.webp"
    assert _frame_summary(output)["frames"] == 2
    with Image.open(output) as img:
        img.seek(1)
        assert "A" in img.convert("RGBA").getbands()


def test_animated_webp_to_gif(runner, tmp_path):
    source = tmp_path / "anim.webp"
    _make_animated_webp(source)
    result = runner.invoke(cli, ["convert", str(source), "-t", "gif", "--json"])
    assert result.exit_code == 0
    summary = _frame_summary(tmp_path / "anim.gif")
    assert summary["frames"] == 2
    # GIF timing is centisecond-based; 80/90ms round-trip exactly.
    assert summary["durations"] == [80, 90]


def test_animated_to_static_format_stays_a_stable_error(runner, tmp_path):
    source = tmp_path / "anim.gif"
    _make_animated_gif(source)
    result = runner.invoke(cli, ["convert", str(source), "-t", "jpg", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["errors"][0]["error"] == "animated_input_not_supported"
    assert not (tmp_path / "anim.jpg").exists()


def test_resize_applies_to_every_frame(tmp_path):
    source = tmp_path / "anim.gif"
    _make_animated_gif(source)
    converter = PixShiftConverter(resize_percent=50, overwrite=True)
    result = converter.convert_single(str(source), str(tmp_path / "half.webp"))
    assert result.success is True
    with Image.open(tmp_path / "half.webp") as img:
        assert img.n_frames == 3
        for frame in ImageSequence.Iterator(img):
            assert frame.size == (16, 16)


def test_still_image_conversion_is_unaffected(runner, tmp_path):
    source = tmp_path / "still.png"
    Image.new("RGB", (20, 20), "purple").save(str(source))
    result = runner.invoke(cli, ["convert", str(source), "-t", "webp", "--json"])
    assert result.exit_code == 0
    with Image.open(tmp_path / "still.webp") as img:
        assert getattr(img, "n_frames", 1) == 1


def test_resize_command_inherits_animation_support(runner, tmp_path):
    source = tmp_path / "anim.gif"
    _make_animated_gif(source)
    result = runner.invoke(cli, ["resize", str(source), "--percent", "50", "--json"])
    assert result.exit_code == 0
    summary = _frame_summary(tmp_path / "anim_resized.gif")
    assert summary["frames"] == 3
    with Image.open(tmp_path / "anim_resized.gif") as img:
        assert img.size == (16, 16)


def test_frame_by_frame_operations_keep_rejecting_animations(runner, tmp_path):
    source = tmp_path / "anim.gif"
    _make_animated_gif(source)
    result = runner.invoke(cli, ["rotate", str(source), "--degrees", "90", "--json"])
    assert result.exit_code == 1
    assert "animated_input_not_supported" in result.output


def test_optimize_recommends_webp_for_animated_gif(runner, tmp_path):
    source = tmp_path / "anim.gif"
    _make_animated_gif(source)
    result = runner.invoke(cli, ["optimize", str(source), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    entry = payload["results"][0]
    assert entry["image_type"] == "animation"
    assert entry["plan"] == {"command": "convert", "arguments": {"to": "webp", "quality": "high"}}
    assert entry["error"] == ""
    _validate(payload, "optimize.json")
    _validate(payload, "envelope.json")


def test_optimize_keeps_animated_webp(runner, tmp_path):
    source = tmp_path / "anim.webp"
    _make_animated_webp(source)
    result = runner.invoke(cli, ["optimize", str(source), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    entry = payload["results"][0]
    assert entry["plan"] == {"command": "keep", "arguments": {}}
    assert entry["recommended_format"] == "keep"
    _validate(payload, "optimize.json")


def test_optimize_plan_applies_end_to_end(runner, tmp_path):
    source = tmp_path / "anim.gif"
    _make_animated_gif(source)
    optimized = runner.invoke(cli, ["optimize", str(source), "--json"])
    assert optimized.exit_code == 0

    applied = runner.invoke(cli, ["apply", "--plan", "-", "--json"], input=optimized.output)
    assert applied.exit_code == 0
    payload = json.loads(applied.output)
    assert payload["applied"] == 1
    step = payload["steps"][0]
    assert step["output"].endswith("anim.webp")
    assert _frame_summary(tmp_path / "anim.webp")["frames"] == 3


def test_optimize_keep_plan_applies_as_skip(runner, tmp_path):
    source = tmp_path / "anim.webp"
    _make_animated_webp(source)
    optimized = runner.invoke(cli, ["optimize", str(source), "--json"])
    applied = runner.invoke(cli, ["apply", "--plan", "-", "--json"], input=optimized.output)
    assert applied.exit_code == 0
    payload = json.loads(applied.output)
    assert payload["skipped"] == 1
    assert payload["steps"][0]["detail"] == "plan_keep"
