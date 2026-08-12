"""Regressions for privacy, animation, transparency, and result semantics."""

import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner
from PIL import Image, features

from pixshift.cli import cli
from pixshift.compare_engine import compare_images
from pixshift.compress_engine import compress_single
from pixshift.converter import PixShiftConverter
from pixshift.crop_engine import crop_single
from pixshift.montage_engine import create_montage
from pixshift.optimize_engine import analyze_image
from pixshift.pdf_engine import pdf_merge_images
from pixshift.strip_engine import analyze_metadata, strip_metadata
from pixshift.watermark_engine import add_image_watermark, add_text_watermark


def _animated_gif(path: Path) -> None:
    """Create a small animation with visibly different frames."""
    frames = [Image.new("RGB", (12, 8), color) for color in ("red", "green", "blue")]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=50, loop=0)


def _animated_png(path: Path) -> None:
    """Create an animated PNG accepted by the compression workflow."""
    frames = [Image.new("RGBA", (12, 8), color) for color in ("red", "green", "blue")]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=50, loop=0)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_default_privacy_strip_removes_nested_sensitive_exif(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    output = tmp_path / "source_clean.jpg"
    exif = Image.Exif()
    exif[271] = "Camera Maker"
    exif[34665] = {
        42032: "Private Owner",
        42033: "Private Serial",
        37510: b"ASCII\x00\x00\x00private note",
        36867: "2025:01:02 03:04:05",
    }
    Image.new("RGB", (16, 16), "red").save(source, exif=exif)

    source_analysis = analyze_metadata(str(source))
    assert source_analysis["has_device"] is True
    assert source_analysis["has_personal"] is True
    assert source_analysis["has_time"] is True

    result = CliRunner().invoke(
        cli,
        ["strip", str(source), "--output", str(tmp_path), "--overwrite", "--json"],
    )

    assert result.exit_code == 0, result.output
    with Image.open(output) as cleaned:
        cleaned_exif = cleaned.getexif()
        nested = cleaned_exif.get_ifd(34665)
        assert 271 not in cleaned_exif
        assert 42032 not in nested
        assert 42033 not in nested
        assert 37510 not in nested
        assert nested[36867] == "2025:01:02 03:04:05"

    analysis = analyze_metadata(str(output))
    assert analysis["has_device"] is False
    assert analysis["has_personal"] is False
    assert analysis["has_time"] is True


def test_convert_animated_same_path_overwrite_preserves_frames(tmp_path: Path) -> None:
    source = tmp_path / "animation.gif"
    _animated_gif(source)
    assert PixShiftConverter.get_image_info(str(source))["frame_count"] == 3

    result = CliRunner().invoke(
        cli,
        ["convert", str(source), "--to", "gif", "--overwrite", "--json"],
    )

    # Animated conversion is supported now; overwriting the source in place
    # must stay atomic and keep every frame (frames are copied to memory
    # before the atomic replace touches the path).
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    with Image.open(source) as image:
        assert image.n_frames == 3


def test_convert_animated_without_overwrite_still_skips_same_path(tmp_path: Path) -> None:
    source = tmp_path / "animation.gif"
    _animated_gif(source)
    original_digest = _sha256(source)

    result = CliRunner().invoke(cli, ["convert", str(source), "--to", "gif", "--json"])

    # Same-path target without --overwrite is an idempotent skip; the
    # source bytes must be untouched.
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["skipped"] == 1
    assert payload["success"] == 0
    assert _sha256(source) == original_digest


@pytest.mark.parametrize(
    "operation",
    [
        lambda source, output: crop_single(str(source), str(output), aspect="1:1", overwrite=True),
        lambda source, output: strip_metadata(str(source), str(output), overwrite=True),
        lambda source, output: add_text_watermark(str(source), str(output), "test", overwrite=True),
    ],
)
def test_static_image_writers_reject_animation(
    tmp_path: Path,
    operation: Callable[[Path, Path], Any],
) -> None:
    source = tmp_path / "animation.gif"
    output = tmp_path / "output.png"
    _animated_gif(source)

    result = operation(source, output)

    assert result.success is False
    assert result.error == "animated_input_not_supported"
    assert not output.exists()


def test_static_image_analyzers_reject_animation(tmp_path: Path) -> None:
    source = tmp_path / "animation.gif"
    second = tmp_path / "second.gif"
    _animated_gif(source)
    _animated_gif(second)

    optimize = analyze_image(str(source))
    comparison = compare_images(str(source), str(second))
    pdf = pdf_merge_images([str(source)], str(tmp_path / "output.pdf"))

    # optimize now classifies animations and plans an executable next step.
    assert optimize.error == ""
    assert optimize.image_type == "animation"
    assert optimize.plan["command"] == "convert"
    assert comparison.success is False
    assert comparison.error == "animated_input_not_supported"
    assert pdf.success is False
    assert pdf.error == "animated_input_not_supported"
    assert not (tmp_path / "output.pdf").exists()


def test_remaining_static_workflows_reject_animation(tmp_path: Path) -> None:
    animation = tmp_path / "animation.gif"
    animated_png = tmp_path / "animation.png"
    still = tmp_path / "still.png"
    _animated_gif(animation)
    _animated_png(animated_png)
    Image.new("RGB", (12, 8), "white").save(still)

    compression = compress_single(
        str(animated_png), str(tmp_path / "compressed.png"), overwrite=True
    )
    montage = create_montage(
        [str(animation), str(still)], str(tmp_path / "montage.png"), overwrite=True
    )
    watermark = add_image_watermark(
        str(still),
        str(tmp_path / "watermarked.png"),
        str(animation),
        overwrite=True,
    )

    for result in (compression, montage, watermark):
        assert result.success is False
        assert result.error == "animated_input_not_supported"
    assert not (tmp_path / "compressed.png").exists()
    assert not (tmp_path / "montage.png").exists()
    assert not (tmp_path / "watermarked.png").exists()


@pytest.mark.skipif(not features.check("webp"), reason="WebP is unavailable")
def test_lossless_compress_preserves_animated_webp_by_exact_copy(tmp_path: Path) -> None:
    source = tmp_path / "animation.webp"
    output = tmp_path / "copy.webp"
    frames = [Image.new("RGB", (12, 8), color) for color in ("red", "green", "blue")]
    frames[0].save(
        source,
        format="WEBP",
        save_all=True,
        append_images=frames[1:],
        duration=50,
        loop=0,
    )

    result = compress_single(str(source), str(output), preset="lossless", overwrite=True)

    assert result.success is True, result.error
    assert _sha256(output) == _sha256(source)
    with Image.open(output) as copied:
        assert copied.n_frames == 3


def test_palette_transparency_is_reported_and_flattened_to_white(tmp_path: Path) -> None:
    source = tmp_path / "indexed.png"
    output = tmp_path / "output.jpg"
    image = Image.new("P", (8, 4), 0)
    image.putpalette([0, 0, 0, 255, 0, 0] + [0, 0, 0] * 254)
    for x in range(4, 8):
        for y in range(4):
            image.putpixel((x, y), 1)
    image.info["transparency"] = 0
    image.save(source)

    converted = PixShiftConverter(overwrite=True).convert_single(str(source), str(output))
    info = PixShiftConverter.get_image_info(str(source))
    optimization = analyze_image(str(source))

    assert converted.success is True, converted.error
    assert info["has_alpha"] is True
    assert info["frame_count"] == 1
    assert optimization.has_alpha is True
    with Image.open(output) as flattened:
        transparent_pixel = flattened.convert("RGB").getpixel((1, 1))
        assert min(transparent_pixel) >= 245


def test_montage_composites_palette_transparency(tmp_path: Path) -> None:
    source = tmp_path / "indexed.png"
    output = tmp_path / "montage.png"
    image = Image.new("P", (8, 4), 0)
    image.putpalette([0, 0, 0, 255, 0, 0] + [0, 0, 0] * 254)
    image.info["transparency"] = 0
    image.save(source)

    result = create_montage(
        [str(source)], str(output), cols=1, gap=0, background="255,255,255", overwrite=True
    )

    assert result.success is True, result.error
    with Image.open(output) as montage:
        assert montage.convert("RGB").getpixel((1, 1)) == (255, 255, 255)


def test_compare_does_not_rate_equal_luminance_colors_as_perfect(tmp_path: Path) -> None:
    red = tmp_path / "red.png"
    green = tmp_path / "green.png"
    Image.new("RGB", (128, 128), (255, 0, 0)).save(red)
    Image.new("RGB", (128, 128), (0, 130, 0)).save(green)

    result = compare_images(str(red), str(green))

    assert result.success is True, result.error
    assert result.mse > 0
    assert result.psnr < 10
    assert result.quality_rating != "完美"


def test_compare_detects_alpha_only_difference(tmp_path: Path) -> None:
    opaque = tmp_path / "opaque.png"
    transparent = tmp_path / "transparent.png"
    Image.new("RGBA", (32, 32), (255, 0, 0, 255)).save(opaque)
    Image.new("RGBA", (32, 32), (255, 0, 0, 0)).save(transparent)

    result = compare_images(str(opaque), str(transparent))

    assert result.success is True, result.error
    assert result.mse > 0
    assert result.quality_rating != "完美"


def test_dedup_empty_analysis_keeps_json_contract(tmp_path: Path) -> None:
    Image.new("RGB", (16, 16), "red").save(tmp_path / "single.png")

    result = CliRunner().invoke(cli, ["dedup", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["mode"] == "analyze"
    assert payload["preview"] == []


def test_dedup_does_not_group_animations_by_first_frame(tmp_path: Path) -> None:
    first = tmp_path / "first.gif"
    second = tmp_path / "second.gif"
    first_frames = [Image.new("RGB", (12, 8), color) for color in ("red", "green", "blue")]
    second_frames = [Image.new("RGB", (12, 8), color) for color in ("red", "white", "black")]
    first_frames[0].save(first, save_all=True, append_images=first_frames[1:], duration=50, loop=0)
    second_frames[0].save(
        second, save_all=True, append_images=second_frames[1:], duration=50, loop=0
    )

    result = CliRunner().invoke(cli, ["dedup", str(tmp_path), "--threshold", "0", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["duplicate_groups"] == 0
    assert payload["deletable_files"] == 0
    assert payload["skipped_invalid"] == 2


def test_dedup_still_finds_byte_identical_animations(tmp_path: Path) -> None:
    first = tmp_path / "first.gif"
    second = tmp_path / "second.gif"
    _animated_gif(first)
    shutil.copyfile(first, second)

    result = CliRunner().invoke(cli, ["dedup", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["duplicate_groups"] == 0
    assert payload["deletable_files"] == 1
    assert payload["skipped_invalid"] == 2
    assert payload["preview"] == []
