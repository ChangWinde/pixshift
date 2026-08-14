"""Regression coverage for PDF semantic and resource-safety boundaries."""

from __future__ import annotations

import io
import json
import random
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image, ImageCms

fitz = pytest.importorskip("pymupdf")

from pixshift import pdf_engine  # noqa: E402
from pixshift.cli import cli  # noqa: E402
from pixshift.pdf_engine import (  # noqa: E402
    PDFPageRangeError,
    _parse_page_range,
    pdf_compress,
    pdf_compress_to_target,
    pdf_concat,
    pdf_extract_pages,
)


def _plain_pdf(path: Path, *, pages: int = 1) -> None:
    with fitz.open() as document:
        for _ in range(pages):
            document.new_page(width=100, height=100)
        document.save(path)


def _noise_image(size: tuple[int, int], mode: str, seed: int) -> Image.Image:
    rng = random.Random(seed)
    width, height = size
    if mode == "1":
        packed = bytes(rng.getrandbits(8) for _ in range((width * height + 7) // 8))
        return Image.frombytes("1", size, packed)
    return Image.frombytes(mode, size, rng.randbytes(width * height * len(mode)))


def _render(path: Path) -> bytes:
    with fitz.open(path) as document:
        return bytes(document[0].get_pixmap(alpha=False).samples)


def _first_embedded_image_profile(path: Path) -> bytes | None:
    with fitz.open(path) as document:
        xref = document[0].get_images(full=True)[0][0]
        payload = document.extract_image(xref)["image"]
    with Image.open(io.BytesIO(payload)) as image:
        return image.info.get("icc_profile")


def test_pdf_merge_and_compress_preserve_functional_icc_profile(tmp_path: Path) -> None:
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    source_image = tmp_path / "profiled.jpg"
    _noise_image((512, 512), "RGB", 17).save(source_image, "JPEG", quality=98, icc_profile=profile)
    merged = tmp_path / "merged.pdf"
    compressed = tmp_path / "compressed.pdf"

    merge_result = pdf_engine.pdf_merge_images([str(source_image)], str(merged))
    compress_result = pdf_compress(str(merged), str(compressed), preset="light")

    assert merge_result.success, merge_result.error
    assert compress_result.success, compress_result.error
    assert _first_embedded_image_profile(merged)
    assert _first_embedded_image_profile(compressed)


def test_pdf_compress_skips_stencil_image_masks(tmp_path: Path) -> None:
    source = tmp_path / "stencil.pdf"
    output = tmp_path / "compressed.pdf"
    buffer = io.BytesIO()
    _noise_image((600, 600), "1", 7).save(buffer, "PNG")

    with fitz.open() as document:
        page = document.new_page(width=200, height=200)
        page.draw_rect(fitz.Rect(20, 20, 92, 92), color=None, fill=(1, 0, 0))
        xref = page.insert_image(fitz.Rect(20, 20, 92, 92), stream=buffer.getvalue())
        document.xref_set_key(xref, "ImageMask", "true")
        document.xref_set_key(xref, "ColorSpace", "null")
        document.save(source)

    before = _render(source)
    result = pdf_compress(str(source), str(output), preset="extreme")

    assert result.success, result.error
    assert result.details["images_replaced"] == 0
    assert result.details["images_skipped"] == 1
    assert _render(output) == before
    with fitz.open(output) as document:
        xref = document[0].get_images(full=True)[0][0]
        assert document.xref_get_key(xref, "ImageMask") == ("bool", "true")


def test_pdf_compress_skips_images_with_nondefault_decode(tmp_path: Path) -> None:
    source = tmp_path / "decode.pdf"
    output = tmp_path / "compressed.pdf"
    buffer = io.BytesIO()
    _noise_image((600, 600), "RGB", 11).save(buffer, "JPEG", quality=95)

    with fitz.open() as document:
        page = document.new_page(width=200, height=200)
        xref = page.insert_image(fitz.Rect(20, 20, 92, 92), stream=buffer.getvalue())
        document.xref_set_key(xref, "Decode", "[1 0 1 0 1 0]")
        document.save(source)

    before = _render(source)
    result = pdf_compress(str(source), str(output), preset="extreme")

    assert result.success, result.error
    assert result.details["images_replaced"] == 0
    assert result.details["images_skipped"] == 1
    assert _render(output) == before
    with fitz.open(output) as document:
        xref = document[0].get_images(full=True)[0][0]
        assert document.xref_get_key(xref, "Decode")[0] == "array"


def _shared_xref_pdf(path: Path, *, large_first: bool) -> None:
    buffer = io.BytesIO()
    _noise_image((400, 400), "RGB", 19).save(buffer, "JPEG", quality=95)
    small = fitz.Rect(20, 20, 92, 92)
    large = fitz.Rect(20, 100, 308, 388)
    first, second = (large, small) if large_first else (small, large)
    with fitz.open() as document:
        page = document.new_page(width=400, height=500)
        xref = page.insert_image(first, stream=buffer.getvalue())
        page = document.new_page(width=400, height=500)
        page.insert_image(second, xref=xref)
        document.save(path)


def _first_image_size(path: Path) -> tuple[int, int]:
    with fitz.open(path) as document:
        xref = document[0].get_images(full=True)[0][0]
        image = document.extract_image(xref)
        return image["width"], image["height"]


def test_shared_xref_downsampling_uses_largest_placement_regardless_of_page_order(
    tmp_path: Path,
) -> None:
    small_first = tmp_path / "small-first.pdf"
    large_first = tmp_path / "large-first.pdf"
    _shared_xref_pdf(small_first, large_first=False)
    _shared_xref_pdf(large_first, large_first=True)

    outputs = []
    for source in (small_first, large_first):
        output = tmp_path / f"{source.stem}-out.pdf"
        result = pdf_compress(
            str(source),
            str(output),
            preset="medium",
            image_quality=60,
            max_image_dpi=150,
        )
        assert result.success, result.error
        outputs.append(output)

    assert _first_image_size(outputs[0]) == _first_image_size(outputs[1]) == (400, 400)


def test_pdf_target_size_creates_a_missing_output_parent(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    _plain_pdf(source)
    with source.open("ab") as stream:
        stream.write(b"padding" * 500)
    output = tmp_path / "new" / "nested" / "output.pdf"

    result = pdf_compress_to_target(str(source), str(output), target_size=800)

    assert result.success, result.error
    assert output.is_file()
    assert output.stat().st_size <= 800


def test_pdf_target_size_integer_search_finds_highest_fitting_quality(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.pdf"
    _plain_pdf(source)
    with source.open("ab") as stream:
        stream.write(b"padding" * 500)

    def fake_rebuild(_doc, destination, image_quality, _max_dpi, _save_opts):
        Path(destination).write_bytes(b"x" * (2 * image_quality + 1))
        return {"images_processed": 1, "images_skipped": 0, "images_replaced": 1}

    monkeypatch.setattr(pdf_engine, "_compress_rebuild", fake_rebuild)
    output = tmp_path / "bounded.pdf"

    result = pdf_compress_to_target(str(source), str(output), target_size=149)

    assert result.success, result.error
    assert result.details["strategy"] == "image_quality_74"
    assert output.stat().st_size == 149


def test_pdf_extract_rejects_render_pixel_budget_before_rasterizing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.pdf"
    _plain_pdf(source)
    output = tmp_path / "pages"
    monkeypatch.setenv("PIXSHIFT_MAX_PIXELS", "9999")

    def unexpected_render(*_args, **_kwargs):
        raise AssertionError("get_pixmap called before enforcing the output pixel budget")

    monkeypatch.setattr(fitz.Page, "get_pixmap", unexpected_render)
    result = pdf_extract_pages(str(source), str(output), dpi=72)

    assert result.success is False
    assert result.error == "image_too_large"
    assert not output.exists()


def test_page_range_errors_are_typed() -> None:
    with pytest.raises(PDFPageRangeError):
        _parse_page_range("0", 2)


@pytest.mark.parametrize("command,pages", [("extract", "0"), ("split", "3")])
def test_pdf_cli_invalid_page_ranges_are_usage_errors(
    tmp_path: Path, command: str, pages: str
) -> None:
    source = tmp_path / "source.pdf"
    _plain_pdf(source, pages=2)
    output = tmp_path / command

    result = CliRunner().invoke(
        cli,
        ["pdf", command, str(source), "--output", str(output), "--pages", pages, "--json"],
    )

    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["error"] == "invalid_page_range"
    assert not output.exists()


def test_pdf_info_password_error_is_stable(tmp_path: Path) -> None:
    source = tmp_path / "locked.pdf"
    with fitz.open() as document:
        document.new_page()
        document.save(
            source,
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="owner",
            user_pw="user",
        )

    result = CliRunner().invoke(cli, ["pdf", "info", str(source), "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["encrypted"] is True
    assert payload["error"] == "pdf_password_required"


def test_pdf_concat_reports_unpreserved_document_semantics(tmp_path: Path) -> None:
    active = tmp_path / "active.pdf"
    plain = tmp_path / "plain.pdf"
    output = tmp_path / "joined.pdf"
    _plain_pdf(plain)
    with fitz.open() as document:
        document.new_page()
        document.set_metadata({"title": "Source title", "author": "Alice"})
        document.embfile_add("payload.bin", b"payload", filename="payload.bin")
        action = document.get_new_xref()
        document.update_object(action, "<< /S /JavaScript /JS (app.alert\\(audit\\)) >>")
        document.xref_set_key(document.pdf_catalog(), "OpenAction", f"{action} 0 R")
        document.xref_set_key(document.pdf_catalog(), "Lang", "(fr-FR)")
        document.xref_set_key(
            document.pdf_catalog(), "ViewerPreferences", "<< /HideToolbar true >>"
        )
        document.xref_set_key(document.pdf_catalog(), "MarkInfo", "<< /Marked true >>")
        document.xref_set_key(document.pdf_catalog(), "OutputIntents", "[]")
        document.set_toc([[1, "Chapter", 1]])
        document.save(active)

    result = pdf_concat([str(active), str(plain)], str(output))

    assert result.success, result.error
    assert {
        "document_metadata_not_preserved",
        "document_embedded_files_not_preserved",
        "document_open_action_not_preserved",
        "document_outline_not_preserved",
        "document_language_not_preserved",
        "document_viewer_preferences_not_preserved",
        "document_names_not_preserved",
        "document_mark_info_not_preserved",
        "document_output_intents_not_preserved",
    } <= set(result.details["warnings"])

    cli_output = tmp_path / "joined-cli.pdf"
    cli_result = CliRunner().invoke(
        cli,
        ["pdf", "concat", str(active), str(plain), "-o", str(cli_output), "--json"],
    )
    assert cli_result.exit_code == 0, cli_result.output
    assert set(result.details["warnings"]) <= set(json.loads(cli_result.output)["warnings"])


def test_pdf_target_size_handles_non_monotonic_encoded_sizes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.pdf"
    _plain_pdf(source)
    with source.open("ab") as stream:
        stream.write(b"padding" * 500)

    def fake_rebuild(_doc, destination, image_quality, _max_dpi, _save_opts):
        size = 149 if image_quality in {46, 49} else 200
        Path(destination).write_bytes(b"x" * size)
        return {"images_processed": 1, "images_skipped": 0, "images_replaced": 1}

    monkeypatch.setattr(pdf_engine, "_compress_rebuild", fake_rebuild)
    output = tmp_path / "bounded.pdf"

    result = pdf_compress_to_target(str(source), str(output), target_size=149)

    assert result.success, result.error
    assert result.details["strategy"] == "image_quality_49"
    assert output.stat().st_size == 149
