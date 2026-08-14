"""Regression tests for metadata-clearing in strip and convert.

Root cause across these bugs: Pillow encoders re-read exif/xmp/comment/icc
from ``img.info`` even when the matching save kwarg is omitted, so skipping a
kwarg is not enough — the info keys must be deleted.
"""

import pytest
from PIL import Image

from pixshift.converter import PixShiftConverter
from pixshift.strip_engine import DEVICE_TAGS, strip_metadata


def _srgb_icc() -> bytes:
    from PIL import ImageCms

    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def test_strip_all_removes_jpeg_comment(tmp_path):
    src = tmp_path / "commented.jpg"
    Image.new("RGB", (32, 32), (200, 40, 40)).save(src, "JPEG", comment=b"secret personal note")
    out = tmp_path / "clean.jpg"

    result = strip_metadata(str(src), str(out), strip_exif=True)

    assert result.success, result.error
    with Image.open(out) as cleaned:
        assert cleaned.info.get("comment") in (None, b"", "")


def test_strip_icc_removes_png_profile(tmp_path):
    src = tmp_path / "profiled.png"
    Image.new("RGB", (32, 32), (10, 120, 200)).save(src, "PNG", icc_profile=_srgb_icc())
    out = tmp_path / "clean.png"

    result = strip_metadata(str(src), str(out), strip_exif=True, strip_icc=True)

    assert result.success, result.error
    with Image.open(out) as cleaned:
        assert not cleaned.info.get("icc_profile")


def test_strip_keeps_png_icc_when_not_requested(tmp_path):
    src = tmp_path / "profiled.png"
    Image.new("RGB", (32, 32), (10, 120, 200)).save(src, "PNG", icc_profile=_srgb_icc())
    out = tmp_path / "kept.png"

    result = strip_metadata(str(src), str(out), strip_exif=True, strip_icc=False)

    assert result.success, result.error
    with Image.open(out) as cleaned:
        assert cleaned.info.get("icc_profile")


def test_device_tag_set_covers_makernote():
    assert "MakerNote" in DEVICE_TAGS
    assert "ImageUniqueID" in DEVICE_TAGS


def test_strip_rgba_named_jpg_does_not_crash(tmp_path):
    # An RGBA image saved with a .jpg name must be flattened, not error out.
    src = tmp_path / "actually_rgba.jpg"
    Image.new("RGBA", (24, 24), (0, 0, 0, 0)).save(src, "PNG")
    out = tmp_path / "clean.jpg"

    result = strip_metadata(str(src), str(out), strip_exif=True)

    assert result.success, result.error
    with Image.open(out) as cleaned:
        assert cleaned.mode == "RGB"


def test_convert_no_exif_clears_png_exif(tmp_path):
    exif = Image.Exif()
    exif[0x010E] = "hidden description"  # ImageDescription
    src = tmp_path / "with_exif.png"
    Image.new("RGB", (32, 32), (5, 5, 5)).save(src, "PNG", exif=exif.tobytes())
    out = tmp_path / "no_exif.png"

    converter = PixShiftConverter(keep_exif=False, keep_icc=True)
    result = converter.convert_single(str(src), str(out))

    assert result.success, result.error
    with Image.open(out) as cleaned:
        assert not dict(cleaned.getexif())


def test_convert_no_icc_clears_png_profile(tmp_path):
    src = tmp_path / "profiled.png"
    Image.new("RGB", (32, 32), (10, 120, 200)).save(src, "PNG", icc_profile=_srgb_icc())
    out = tmp_path / "no_icc.png"

    converter = PixShiftConverter(keep_exif=True, keep_icc=False)
    result = converter.convert_single(str(src), str(out))

    assert result.success, result.error
    with Image.open(out) as cleaned:
        assert not cleaned.info.get("icc_profile")


def test_convert_cmyk_to_png_succeeds_and_drops_stale_icc(tmp_path):
    src = tmp_path / "cmyk.tiff"
    # Attach an ICC that describes the CMYK data; after CMYK->RGB it is invalid.
    Image.new("CMYK", (32, 32), (0, 0, 0, 0)).save(
        src, "TIFF", icc_profile=b"fake-cmyk-profile-bytes"
    )
    out = tmp_path / "converted.png"

    converter = PixShiftConverter(keep_exif=True, keep_icc=True)
    result = converter.convert_single(str(src), str(out))

    assert result.success, result.error
    with Image.open(out) as cleaned:
        assert cleaned.mode == "RGB"
        assert not cleaned.info.get("icc_profile")


@pytest.mark.parametrize("fmt,ext", [("HEIF", ".heic")])
def test_strip_all_removes_heic_metadata(tmp_path, fmt, ext):
    heif = pytest.importorskip("pillow_heif")
    heif.register_heif_opener()

    exif = Image.Exif()
    exif[0x0110] = "SecretPhone"  # Model
    src = tmp_path / f"photo{ext}"
    Image.new("RGB", (48, 48), (120, 120, 120)).save(
        src, fmt, exif=exif.tobytes(), xmp=b"<x:xmpmeta>gps here</x:xmpmeta>"
    )
    out = tmp_path / f"clean{ext}"

    result = strip_metadata(str(src), str(out), strip_exif=True)

    assert result.success, result.error
    with Image.open(out) as cleaned:
        assert not dict(cleaned.getexif())
        assert not cleaned.info.get("xmp")
