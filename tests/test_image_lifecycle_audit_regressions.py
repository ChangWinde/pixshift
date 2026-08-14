"""Regression coverage for the image-lifecycle deep-audit findings."""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image, ImageChops, ImageCms, ImageDraw

from pixshift import compress_engine
from pixshift.cli import cli
from pixshift.compress_engine import compress_single
from pixshift.converter import PixShiftConverter
from pixshift.crop_engine import crop_single
from pixshift.optimize_engine import analyze_image
from pixshift.strip_engine import strip_metadata
from pixshift.transform_engine import rotate_image
from pixshift.watermark_engine import add_image_watermark


def _noise(size: tuple[int, int] = (128, 128)) -> Image.Image:
    rng = random.Random(12345)
    payload = bytes(rng.randrange(256) for _ in range(size[0] * size[1] * 3))
    return Image.frombytes("RGB", size, payload)


def test_target_size_copies_an_input_that_already_fits_byte_for_byte(tmp_path: Path) -> None:
    source = tmp_path / "lossless.webp"
    _noise().save(source, "WEBP", lossless=True, method=6)
    output = tmp_path / "lossless_compressed.webp"

    result = compress_single(
        str(source),
        str(output),
        target_size=f"{source.stat().st_size + 1000}B",
        overwrite=True,
    )

    assert result.success, result.error
    assert output.read_bytes() == source.read_bytes()


def test_image_target_size_handles_non_monotonic_encoded_sizes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.jpg"
    output = tmp_path / "bounded.jpg"
    Image.new("RGB", (16, 16), "red").save(source, "JPEG")
    with source.open("ab") as stream:
        stream.write(b"padding" * 500)

    def fake_encode(_image, _ext, _config, quality):
        return b"x" * (334 if quality == 10 else 335 if quality == 9 else 400)

    monkeypatch.setattr(compress_engine, "_encode_compressed", fake_encode)

    result = compress_single(str(source), str(output), target_size="334B", overwrite=True)

    assert result.success, result.error
    assert result.quality_used == 10
    assert output.stat().st_size == 334


@pytest.mark.parametrize(("format_name", "suffix"), [("PNG", ".png"), ("TIFF", ".tiff")])
def test_lossless_target_size_never_resizes_to_reach_budget(
    tmp_path: Path,
    format_name: str,
    suffix: str,
) -> None:
    source = tmp_path / f"noise{suffix}"
    _noise((64, 64)).save(source, format_name)
    output = tmp_path / f"out{suffix}"

    result = compress_single(str(source), str(output), target_size="1000B", overwrite=True)

    assert not result.success
    assert "target_size_unreachable" in result.error
    assert not output.exists()


def test_apng_default_image_is_not_inserted_into_webp_animation(tmp_path: Path) -> None:
    source = tmp_path / "poster.apng"
    poster = Image.new("RGBA", (8, 8), "red")
    green = Image.new("RGBA", (8, 8), "green")
    blue = Image.new("RGBA", (8, 8), "blue")
    poster.save(
        source,
        "PNG",
        save_all=True,
        append_images=[green, blue],
        default_image=True,
        duration=[110, 220],
        loop=0,
    )
    output = tmp_path / "animation.webp"

    result = PixShiftConverter(overwrite=True).convert_single(str(source), str(output))

    assert result.success, result.error
    with Image.open(output) as converted:
        assert converted.n_frames == 2
        pixels = []
        durations = []
        for frame_number in range(converted.n_frames):
            converted.seek(frame_number)
            pixels.append(converted.convert("RGB").getpixel((0, 0)))
            durations.append(converted.info.get("duration"))
    assert pixels[0][1] > 120 and pixels[0][0] < 15
    assert pixels[1][2] > 240 and pixels[1][0] < 15
    assert durations == [110, 220]


def test_apng_default_image_semantics_survive_apng_reencode(tmp_path: Path) -> None:
    source = tmp_path / "poster.apng"
    frames = [
        Image.new("RGBA", (8, 8), "red"),
        Image.new("RGBA", (8, 8), "green"),
        Image.new("RGBA", (8, 8), "blue"),
    ]
    frames[0].save(
        source,
        "PNG",
        save_all=True,
        append_images=frames[1:],
        default_image=True,
        duration=[70, 90],
        loop=2,
    )
    output = tmp_path / "reencoded.png"

    result = PixShiftConverter(overwrite=True).convert_single(str(source), str(output))

    assert result.success, result.error
    with Image.open(output) as converted:
        assert converted.info.get("default_image") is True
        assert converted.info.get("loop") == 2
        assert converted.n_frames == 3
        converted.seek(1)
        assert converted.info.get("duration") == pytest.approx(70, abs=1)
        converted.seek(2)
        assert converted.info.get("duration") == pytest.approx(90, abs=1)


def test_missing_gif_loop_is_preserved_as_single_play_when_converting(tmp_path: Path) -> None:
    source = tmp_path / "once.gif"
    frames = [Image.new("RGB", (8, 8), "red"), Image.new("RGB", (8, 8), "blue")]
    frames[0].save(
        source,
        "GIF",
        save_all=True,
        append_images=frames[1:],
        duration=[60, 80],
    )
    with Image.open(source) as original:
        assert original.info.get("loop") is None
    output = tmp_path / "once.webp"

    result = PixShiftConverter(overwrite=True).convert_single(str(source), str(output))

    assert result.success, result.error
    with Image.open(output) as converted:
        assert converted.info.get("loop") == 1


def test_webp_to_gif_rejects_unrepresentable_frame_timing(tmp_path: Path) -> None:
    source = tmp_path / "precise.webp"
    output = tmp_path / "rounded.gif"
    frames = [Image.new("RGB", (8, 8), "red"), Image.new("RGB", (8, 8), "blue")]
    frames[0].save(
        source,
        "WEBP",
        save_all=True,
        append_images=frames[1:],
        duration=[15, 15],
        loop=0,
        lossless=True,
    )

    result = PixShiftConverter(overwrite=True).convert_single(str(source), str(output))

    assert result.success is False
    assert result.error == "animation_timing_not_representable:gif"
    assert not output.exists()


def test_multi_page_tiff_is_not_reinterpreted_as_animation(tmp_path: Path) -> None:
    source = tmp_path / "pages.tiff"
    pages = [Image.new("RGB", (8, 8), "red"), Image.new("RGB", (8, 8), "blue")]
    pages[0].save(source, "TIFF", save_all=True, append_images=pages[1:])
    output = tmp_path / "pages.webp"

    converted = PixShiftConverter(overwrite=True).convert_single(str(source), str(output))
    optimized = analyze_image(str(source))

    assert not converted.success
    assert converted.error == "animated_input_not_supported"
    assert not output.exists()
    assert optimized.error == "animated_input_not_supported"
    assert optimized.plan == {}


def test_optimize_applies_pixel_budget_to_the_whole_animation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "many.gif"
    frames = [Image.new("RGB", (6, 6), color) for color in ("red", "blue", "green", "white")]
    frames[0].save(source, "GIF", save_all=True, append_images=frames[1:], duration=50)
    monkeypatch.setenv("PIXSHIFT_MAX_PIXELS", "100")

    result = analyze_image(str(source))

    assert result.error.startswith("image_too_large")
    assert result.plan == {}


def test_resize_rejects_an_output_over_the_pixel_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "small.png"
    Image.new("RGB", (5, 5), "green").save(source)
    output = tmp_path / "oversized.png"
    monkeypatch.setenv("PIXSHIFT_MAX_PIXELS", "100")

    result = PixShiftConverter(resize=(11, 10), overwrite=True).convert_single(
        str(source), str(output)
    )

    assert not result.success
    assert result.error.startswith("image_too_large")
    assert not output.exists()


def test_trim_uses_alpha_as_visible_content_mask(tmp_path: Path) -> None:
    source = tmp_path / "transparent.png"
    image = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((5, 6, 14, 15), fill=(0, 0, 0, 255))
    source_image = image.copy()
    image.save(source)
    output = tmp_path / "trimmed.png"

    result = crop_single(str(source), str(output), trim=True, trim_fuzz=0, overwrite=True)

    assert result.success, result.error
    assert result.crop_box == (3, 4, 17, 18)
    assert result.cropped_size == (14, 14)
    with Image.open(output) as trimmed:
        expected = source_image.crop(result.crop_box)
        assert ImageChops.difference(trimmed.convert("RGBA"), expected).getbbox() is None


def test_image_watermark_applies_requested_opacity_once(tmp_path: Path) -> None:
    source = tmp_path / "base.png"
    watermark = tmp_path / "logo.png"
    output = tmp_path / "watermarked.png"
    Image.new("RGB", (4, 4), "black").save(source)
    Image.new("RGBA", (4, 4), "white").save(watermark)

    result = add_image_watermark(
        str(source),
        str(output),
        str(watermark),
        scale=1,
        opacity=128,
        position="center",
        margin=0,
        overwrite=True,
    )

    assert result.success, result.error
    with Image.open(output) as watermarked:
        assert watermarked.convert("RGB").getpixel((2, 2)) == (128, 128, 128)


def _inject_iptc_resource(path: Path) -> None:
    data = b"secret-iptc-caption"
    resource = b"8BIM" + (0x0404).to_bytes(2, "big") + b"\x00\x00"
    resource += len(data).to_bytes(4, "big") + data
    if len(data) % 2:
        resource += b"\x00"
    payload = b"Photoshop 3.0\x00" + resource
    segment = b"\xff\xed" + (len(payload) + 2).to_bytes(2, "big") + payload
    encoded = path.read_bytes()
    path.write_bytes(encoded[:2] + segment + encoded[2:])


def test_privacy_mode_covers_document_identifiers_xmp_and_iptc(tmp_path: Path) -> None:
    from pixshift.strip_engine import resolve_strip_mode

    source = tmp_path / "private.jpg"
    exif = Image.Exif()
    exif[269] = "secret-document-name"
    exif[285] = "secret-page-name"
    exif[306] = "2020:01:02 03:04:05"
    Image.new("RGB", (16, 16), "gray").save(
        source,
        "JPEG",
        exif=exif,
        xmp=b"<x:xmpmeta>secret-person-name</x:xmpmeta>",
    )
    _inject_iptc_resource(source)
    with Image.open(source) as original:
        assert original.info.get("xmp")
        assert original.info.get("photoshop")
    output = tmp_path / "private_clean.jpg"
    flags = resolve_strip_mode("privacy")

    result = strip_metadata(
        str(source),
        str(output),
        strip_exif=flags[0],
        strip_gps=flags[1],
        strip_device=flags[2],
        strip_personal=flags[3],
        strip_time=flags[4],
        overwrite=True,
    )

    assert result.success, result.error
    with Image.open(output) as cleaned:
        remaining = cleaned.getexif()
        assert 269 not in remaining
        assert 285 not in remaining
        assert remaining.get(306) == "2020:01:02 03:04:05"
        assert not cleaned.info.get("xmp")
        assert not cleaned.info.get("photoshop")


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("privacy", (False, True, True, True, False)),
        ("all", (True, False, False, False, False)),
        ("gps", (False, True, False, False, False)),
        ("device", (False, False, True, False, False)),
        ("personal", (False, False, False, True, False)),
        ("time", (False, False, False, False, True)),
    ],
)
def test_resolve_strip_mode_is_the_canonical_policy(mode: str, expected: tuple[bool, ...]) -> None:
    from pixshift.strip_engine import resolve_strip_mode

    assert resolve_strip_mode(mode) == expected
    assert resolve_strip_mode(mode.upper()) == expected


def test_resolve_strip_mode_rejects_unknown_policy() -> None:
    from pixshift.strip_engine import resolve_strip_mode

    with pytest.raises(ValueError, match="unsupported_strip_mode:unknown"):
        resolve_strip_mode("unknown")


def test_lab_to_png_uses_embedded_profile_and_embeds_srgb(tmp_path: Path) -> None:
    source = tmp_path / "lab.tiff"
    lab_profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB"))
    srgb_profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    Image.new("LAB", (8, 8), (150, 140, 115)).save(
        source,
        "TIFF",
        icc_profile=lab_profile.tobytes(),
    )
    with Image.open(source) as opened:
        expected = ImageCms.profileToProfile(
            opened,
            lab_profile,
            srgb_profile,
            outputMode="RGB",
        ).copy()
    output = tmp_path / "lab.png"

    result = PixShiftConverter(overwrite=True).convert_single(str(source), str(output))

    assert result.success, result.error
    with Image.open(output) as converted:
        assert converted.mode == "RGB"
        assert converted.info.get("icc_profile")
        assert ImageChops.difference(converted, expected).getbbox() is None


def test_cmyk_watermark_does_not_relabel_rgb_pixels_with_cmyk_profile(tmp_path: Path) -> None:
    source = tmp_path / "cmyk.tiff"
    watermark = tmp_path / "logo.png"
    output = tmp_path / "watermarked.png"
    Image.new("CMYK", (16, 16), (0, 128, 128, 0)).save(
        source,
        "TIFF",
        icc_profile=b"invalid-cmyk-profile",
    )
    Image.new("RGBA", (4, 4), (255, 255, 255, 255)).save(watermark)

    result = add_image_watermark(
        str(source),
        str(output),
        str(watermark),
        opacity=255,
        overwrite=True,
    )

    assert result.success, result.error
    with Image.open(output) as converted:
        assert converted.mode in {"RGB", "RGBA"}
        assert not converted.info.get("icc_profile")


@pytest.mark.parametrize("operation", ["convert", "crop", "rotate"])
def test_cmyk_to_png_operations_drop_an_invalid_source_profile(
    tmp_path: Path,
    operation: str,
) -> None:
    source = tmp_path / "cmyk.tiff"
    output = tmp_path / f"{operation}.png"
    Image.new("CMYK", (16, 12), (0, 128, 128, 0)).save(
        source,
        "TIFF",
        icc_profile=b"invalid-cmyk-profile",
    )

    if operation == "convert":
        result = PixShiftConverter(overwrite=True).convert_single(str(source), str(output))
    elif operation == "crop":
        result = crop_single(
            str(source),
            str(output),
            crop_box="0,0,8,8",
            overwrite=True,
        )
    else:
        result = rotate_image(str(source), str(output), degrees=90, overwrite=True)

    assert result.success, result.error
    with Image.open(output) as converted:
        assert converted.mode == "RGB"
        assert not converted.info.get("icc_profile")


def test_explicit_srgb_policy_embeds_profile_for_untagged_rgb(tmp_path: Path) -> None:
    source = tmp_path / "untagged.png"
    output = tmp_path / "srgb.png"
    Image.new("RGB", (12, 8), (20, 90, 180)).save(source)

    result = PixShiftConverter(color_space="srgb", overwrite=True).convert_single(
        str(source), str(output)
    )

    assert result.success, result.error
    with Image.open(output) as converted:
        assert converted.mode == "RGB"
        assert converted.info.get("icc_profile")


def test_preserve_policy_keeps_cmyk_for_capable_jpeg_output(tmp_path: Path) -> None:
    source = tmp_path / "source.tiff"
    output = tmp_path / "preserved.jpg"
    Image.new("CMYK", (12, 8), (10, 20, 30, 40)).save(source, "TIFF")

    result = PixShiftConverter(overwrite=True, color_space="preserve").convert_single(
        str(source), str(output)
    )

    assert result.success, result.error
    with Image.open(output) as converted:
        assert converted.mode == "CMYK"


def test_explicit_srgb_policy_rejects_invalid_embedded_profile(tmp_path: Path) -> None:
    source = tmp_path / "invalid-profile.png"
    output = tmp_path / "srgb.png"
    Image.new("RGB", (12, 8), (20, 90, 180)).save(source, icc_profile=b"not-an-icc-profile")

    result = PixShiftConverter(color_space="srgb", overwrite=True).convert_single(
        str(source), str(output)
    )

    assert result.success is False
    assert result.error == "invalid_icc_profile"
    assert output.exists() is False


@pytest.mark.parametrize("mode", ["P", "LA", "RGBA"])
def test_explicit_srgb_policy_preserves_every_transparency_representation(
    tmp_path: Path, mode: str
) -> None:
    source = tmp_path / f"transparent-{mode}.png"
    output = tmp_path / f"converted-{mode}.png"
    if mode == "P":
        image = Image.new("P", (2, 1))
        image.putpalette([255, 0, 0, 0, 255, 0] + [0, 0, 0] * 254)
        image.putdata([0, 1])
        image.info["transparency"] = 0
    elif mode == "LA":
        image = Image.new("LA", (2, 1))
        image.putdata([(80, 0), (80, 255)])
    else:
        image = Image.new("RGBA", (2, 1))
        image.putdata([(255, 0, 0, 0), (0, 255, 0, 255)])
    image.save(source)

    result = PixShiftConverter(color_space="srgb", overwrite=True).convert_single(
        str(source), str(output)
    )

    assert result.success, result.error
    with Image.open(output) as converted:
        assert converted.mode == "RGBA"
        assert converted.getchannel("A").getextrema() == (0, 255)
        assert "transparency" not in converted.info


def test_prep_default_srgb_accepts_indexed_transparency(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source = source_dir / "indexed.png"
    image = Image.new("P", (2, 1))
    image.putpalette([255, 0, 0, 0, 255, 0] + [0, 0, 0] * 254)
    image.putdata([0, 1])
    image.info["transparency"] = 0
    image.save(source)
    output_dir = tmp_path / "prepared"

    result = CliRunner().invoke(
        cli,
        ["prep", str(source_dir), "-o", str(output_dir), "--to", "png", "--json"],
    )

    assert result.exit_code == 0, result.output
    with Image.open(output_dir / "indexed.png") as prepared:
        assert prepared.mode == "RGBA"
        assert prepared.getchannel("A").getextrema() == (0, 255)
