"""Tests for the pdf merge JPEG splice fast path and its privacy invariant."""

import io

import pymupdf as fitz
import pytest
from PIL import Image

from pixshift.pdf_engine import (
    _strip_jpeg_metadata,
    pdf_merge_images,
)


def _make_jpeg(path, *, quality=90, exif=False, comment=False, orientation=None, mode="RGB"):
    img = Image.new(mode, (120, 80))
    for x in range(120):
        for y in range(80):
            img.putpixel((x, y), (x * 2, y * 3, (x + y) % 255) if mode == "RGB" else (x + y) % 255)
    params = {"format": "JPEG", "quality": quality}
    if exif or orientation:
        tags = Image.Exif()
        tags[271] = "PixCam"  # Make
        tags[272] = "SecretModel 9"  # Model
        if orientation:
            tags[274] = orientation
        params["exif"] = tags.tobytes()
    if comment:
        params["comment"] = b"secret-comment"
    img.save(str(path), **params)


def _embedded_image(pdf_path):
    with fitz.open(str(pdf_path)) as doc:
        xref = doc.get_page_images(0)[0][0]
        payload = doc.extract_image(xref)
        return payload["image"], payload["ext"]


def test_clean_jpeg_is_spliced_byte_identical(tmp_path):
    source = tmp_path / "photo.jpg"
    _make_jpeg(source)
    raw = source.read_bytes()

    result = pdf_merge_images([str(source)], str(tmp_path / "out.pdf"))
    assert result.success is True

    embedded, ext = _embedded_image(tmp_path / "out.pdf")
    assert ext in ("jpeg", "jpg")
    assert embedded == _strip_jpeg_metadata(raw)


def test_splice_strips_exif_and_comments_from_the_pdf(tmp_path):
    source = tmp_path / "tagged.jpg"
    _make_jpeg(source, exif=True, comment=True)
    raw = source.read_bytes()
    assert b"Exif" in raw
    assert b"secret-comment" in raw

    result = pdf_merge_images([str(source)], str(tmp_path / "out.pdf"))
    assert result.success is True

    embedded, _ = _embedded_image(tmp_path / "out.pdf")
    assert b"Exif" not in embedded
    assert b"SecretModel" not in embedded
    assert b"secret-comment" not in embedded


def test_strip_is_pixel_lossless():
    buffer = io.BytesIO()
    img = Image.new("RGB", (64, 64), "orange")
    tags = Image.Exif()
    tags[271] = "PixCam"
    img.save(buffer, format="JPEG", quality=85, exif=tags.tobytes(), comment=b"note")
    raw = buffer.getvalue()

    stripped = _strip_jpeg_metadata(raw)
    assert stripped is not None
    assert len(stripped) < len(raw)
    with Image.open(io.BytesIO(raw)) as before, Image.open(io.BytesIO(stripped)) as after:
        assert before.tobytes() == after.tobytes()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw[:-2] + b"\xff\xfe\x00\x12secret-after-sos" + raw[-2:],
        lambda raw: raw + b"secret-after-eoi",
    ],
)
def test_splice_rejects_metadata_or_trailing_bytes_after_scan(tmp_path, mutate):
    source = tmp_path / "tainted.jpg"
    _make_jpeg(source, quality=95)
    source.write_bytes(mutate(source.read_bytes()))
    assert _strip_jpeg_metadata(source.read_bytes()) is None

    result = pdf_merge_images([str(source)], str(tmp_path / "out.pdf"))
    assert result.success is True
    embedded, _ = _embedded_image(tmp_path / "out.pdf")
    assert b"secret-after" not in embedded


def test_progressive_jpeg_uses_safe_reencode_fallback(tmp_path):
    source = tmp_path / "progressive.jpg"
    Image.new("RGB", (120, 80), "purple").save(source, format="JPEG", progressive=True)
    assert _strip_jpeg_metadata(source.read_bytes()) is None

    result = pdf_merge_images([str(source)], str(tmp_path / "out.pdf"))
    assert result.success is True


@pytest.mark.parametrize(
    "data",
    [b"", b"\xff\xd8", b"not a jpeg at all", b"\xff\xd8\xff\xe1\x00\x05ab"],
)
def test_strip_rejects_malformed_streams(data):
    assert _strip_jpeg_metadata(data) is None


def test_explicit_recompression_still_reencodes(tmp_path):
    source = tmp_path / "photo.jpg"
    _make_jpeg(source, quality=95)
    raw = source.read_bytes()

    result = pdf_merge_images([str(source)], str(tmp_path / "out.pdf"), quality=60)
    assert result.success is True

    embedded, _ = _embedded_image(tmp_path / "out.pdf")
    assert embedded != _strip_jpeg_metadata(raw)
    assert len(embedded) < len(raw)


def test_oriented_jpeg_goes_through_normalisation(tmp_path):
    source = tmp_path / "rotated.jpg"
    _make_jpeg(source, orientation=6)
    raw = source.read_bytes()

    result = pdf_merge_images([str(source)], str(tmp_path / "out.pdf"), page_size="fit")
    assert result.success is True

    embedded, _ = _embedded_image(tmp_path / "out.pdf")
    assert embedded != _strip_jpeg_metadata(raw)
    # Orientation 6 rotates 90 degrees: the fit page must be portrait now.
    with fitz.open(str(tmp_path / "out.pdf")) as doc:
        rect = doc[0].rect
        assert rect.height > rect.width


def test_grayscale_jpeg_is_spliced(tmp_path):
    source = tmp_path / "gray.jpg"
    _make_jpeg(source, mode="L")
    raw = source.read_bytes()

    result = pdf_merge_images([str(source)], str(tmp_path / "out.pdf"))
    assert result.success is True
    embedded, _ = _embedded_image(tmp_path / "out.pdf")
    assert embedded == _strip_jpeg_metadata(raw)


def test_png_with_alpha_keeps_the_png_path(tmp_path):
    source = tmp_path / "alpha.png"
    Image.new("RGBA", (40, 40), (255, 0, 0, 128)).save(str(source))

    result = pdf_merge_images([str(source)], str(tmp_path / "out.pdf"))
    assert result.success is True


def test_compress_extreme_downscales_dense_pages(tmp_path):
    """The per-page rect index must keep the DPI downscale path working."""
    from pixshift.pdf_engine import pdf_compress

    buffer = io.BytesIO()
    big = Image.new("RGB", (1600, 1600))
    for x in range(0, 1600, 16):
        for y in range(0, 1600, 16):
            big.paste(((x * 7) % 255, (y * 5) % 255, (x + y) % 255), (x, y, x + 16, y + 16))
    big.save(buffer, format="JPEG", quality=92)
    payload = buffer.getvalue()

    source = tmp_path / "dense.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        # Several placements of the same and distinct images at ~100pt,
        # which puts the effective resolution far above extreme's DPI cap.
        for index in range(4):
            rect = fitz.Rect(20 + index * 140, 20, 120 + index * 140, 120)
            page.insert_image(rect, stream=payload)
        doc.save(str(source))

    result = pdf_compress(str(source), str(tmp_path / "small.pdf"), preset="extreme")
    assert result.success is True

    with fitz.open(str(tmp_path / "small.pdf")) as doc:
        xref = doc.get_page_images(0)[0][0]
        replaced = doc.extract_image(xref)
        assert replaced["width"] < 1600
    assert (tmp_path / "small.pdf").stat().st_size < source.stat().st_size
