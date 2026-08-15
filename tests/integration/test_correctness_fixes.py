"""Regression tests for compress/PDF correctness fixes (A2/A3)."""

import io

import pytest
from PIL import Image

from pixshift.compress_engine import compress_single

fitz = pytest.importorskip("pymupdf")

from pixshift.pdf_engine import pdf_compress, pdf_extract_pages, pdf_split  # noqa: E402


def test_compress_never_grows_a_jpeg(tmp_path):
    # A q30 JPEG re-encoded at a higher preset would grow; compress must not.
    src = tmp_path / "low.jpg"
    Image.effect_noise((256, 256), 40).convert("RGB").save(src, "JPEG", quality=30)
    input_size = src.stat().st_size
    out = tmp_path / "compressed.jpg"

    result = compress_single(str(src), str(out), preset="high", overwrite=True)

    assert result.success, result.error
    assert out.stat().st_size <= input_size


def test_compress_lossless_webp_with_resize_succeeds(tmp_path):
    src = tmp_path / "big.webp"
    Image.effect_noise((400, 400), 60).convert("RGB").save(src, "WEBP", quality=90)
    out = tmp_path / "small.webp"

    result = compress_single(str(src), str(out), preset="lossless", max_size=100, overwrite=True)

    assert result.success, result.error
    with Image.open(out) as small:
        assert max(small.size) <= 100
        assert small.format == "WEBP"


def _encrypted_pdf(path):
    doc = fitz.open()
    doc.new_page(width=200, height=200)
    doc.save(
        str(path),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner",
        user_pw="user",
    )
    doc.close()


def test_pdf_split_rejects_password_locked_pdf(tmp_path):
    src = tmp_path / "locked.pdf"
    _encrypted_pdf(src)
    out_dir = tmp_path / "pages"

    result = pdf_split(str(src), str(out_dir))

    assert not result.success
    assert result.error == "pdf_password_required"


def test_pdf_extract_rejects_password_locked_pdf(tmp_path):
    src = tmp_path / "locked.pdf"
    _encrypted_pdf(src)
    out_dir = tmp_path / "imgs"

    result = pdf_extract_pages(str(src), str(out_dir))

    assert not result.success
    assert result.error == "pdf_password_required"


def _pdf_with_transparent_image(path):
    rgba = Image.new("RGBA", (80, 80), (200, 40, 40, 120))
    buf = io.BytesIO()
    rgba.save(buf, "PNG")
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_image(fitz.Rect(10, 10, 90, 90), stream=buf.getvalue())
    doc.save(str(path))
    doc.close()


def test_pdf_compress_preserves_soft_masked_image(tmp_path):
    src = tmp_path / "transparent.pdf"
    _pdf_with_transparent_image(src)
    out = tmp_path / "compressed.pdf"

    result = pdf_compress(str(src), str(out), preset="medium")
    assert result.success, result.error

    # The soft mask (transparency) must survive compression, not be flattened.
    doc = fitz.open(str(out))
    has_soft_masked_image = any(
        doc.extract_image(xref).get("smask", 0)
        for page in doc
        for xref, *_ in page.get_images(full=True)
    )
    doc.close()
    assert has_soft_masked_image


def _pdf_with_colour_key_mask(path):
    image = Image.new("RGB", (160, 80), (128, 0, 0))
    for x in range(80, 160):
        for y in range(80):
            image.putpixel((x, y), (0, 0, 200))
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=95)
    doc = fitz.open()
    page = doc.new_page(width=160, height=80)
    xref = page.insert_image(page.rect, stream=buf.getvalue())
    doc.xref_set_key(xref, "Mask", "[120 136 0 255 0 255]")
    doc.save(path)
    doc.close()


def _transparent_pixels(path) -> int:
    with fitz.open(path) as doc:
        pixmap = doc[0].get_pixmap(alpha=True)
        return sum(alpha < 255 for alpha in pixmap.samples[3::4])


def test_pdf_compress_preserves_colour_key_masked_image(tmp_path):
    src = tmp_path / "masked.pdf"
    out = tmp_path / "compressed.pdf"
    _pdf_with_colour_key_mask(src)
    before = _transparent_pixels(src)

    result = pdf_compress(str(src), str(out), preset="extreme")

    assert result.success, result.error
    assert result.details["images_replaced"] == 0
    assert result.details["images_skipped"] == 1
    assert before > 0
    assert _transparent_pixels(out) == before
    with fitz.open(out) as doc:
        xref = doc[0].get_images(full=True)[0][0]
        assert doc.xref_get_key(xref, "Mask")[0] != "null"
