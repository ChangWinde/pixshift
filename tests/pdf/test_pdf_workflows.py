"""Successful CLI journeys for every PDF transformation command."""

import json
from pathlib import Path

import fitz
from click.testing import CliRunner
from PIL import Image

from pixshift.cli import cli
from pixshift.pdf_engine import pdf_concat, pdf_merge_images


def _one_page_pdf(path: Path, label: str) -> None:
    document = fitz.open()
    page = document.new_page(width=100, height=100)
    page.insert_text((10, 50), label)
    document.save(path)
    document.close()


def test_concat_rejects_an_output_that_is_also_an_input(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    third = tmp_path / "third.pdf"
    _one_page_pdf(first, "ORIGINAL-A")
    _one_page_pdf(second, "B")
    _one_page_pdf(third, "C")
    original_bytes = first.read_bytes()

    result = CliRunner().invoke(
        cli,
        [
            "pdf",
            "concat",
            str(first),
            str(second),
            str(third),
            "--output",
            str(first),
            "--overwrite",
            "--json",
        ],
    )

    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["error"] == "output_collision"
    assert first.read_bytes() == original_bytes


def test_merge_rejects_an_output_that_is_also_an_input(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (16, 16), "red").save(source)
    original_bytes = source.read_bytes()

    cli_result = CliRunner().invoke(
        cli,
        [
            "pdf",
            "merge",
            str(source),
            "--output",
            str(source),
            "--overwrite",
            "--page",
            "fit",
            "--margin",
            "0",
            "--json",
        ],
    )
    engine_result = pdf_merge_images([str(source)], str(source), overwrite=True)

    assert cli_result.exit_code == 2, cli_result.output
    assert json.loads(cli_result.output)["error"] == "output_collision"
    assert engine_result.success is False
    assert engine_result.error == "output_collision"
    assert source.read_bytes() == original_bytes


def test_concat_engine_rejects_an_output_that_is_also_an_input(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    _one_page_pdf(first, "A")
    _one_page_pdf(second, "B")
    original_bytes = first.read_bytes()

    result = pdf_concat([str(first), str(second)], str(first), overwrite=True)

    assert result.success is False
    assert result.error == "output_collision"
    assert first.read_bytes() == original_bytes


def test_concat_rejects_a_scanned_input_as_the_output(tmp_path: Path) -> None:
    source_dir = tmp_path / "pdfs"
    source_dir.mkdir()
    first = source_dir / "first.pdf"
    second = source_dir / "second.pdf"
    _one_page_pdf(first, "REAL-A")
    _one_page_pdf(second, "B")
    original_bytes = first.read_bytes()

    result = CliRunner().invoke(
        cli,
        [
            "pdf",
            "concat",
            str(source_dir),
            "--output",
            str(first),
            "--overwrite",
            "--json",
        ],
    )

    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["error"] == "output_collision"
    assert first.read_bytes() == original_bytes


def test_pdf_transform_workflow(tmp_path: Path) -> None:
    runner = CliRunner()
    images = tmp_path / "images"
    images.mkdir()
    Image.new("RGB", (80, 60), "red").save(images / "one.jpg")
    Image.new("RGB", (80, 60), "blue").save(images / "two.jpg")

    first_pdf = tmp_path / "first.pdf"
    merged = runner.invoke(cli, ["pdf", "merge", str(images), "--output", str(first_pdf), "--json"])
    assert merged.exit_code == 0, merged.output
    assert json.loads(merged.output)["page_count"] == 2

    extracted_dir = tmp_path / "extracted"
    extracted = runner.invoke(
        cli,
        [
            "pdf",
            "extract",
            str(first_pdf),
            "--output",
            str(extracted_dir),
            "--pages",
            "1",
            "--json",
        ],
    )
    assert extracted.exit_code == 0, extracted.output
    assert json.loads(extracted.output)["exported_pages"] == 1
    assert (extracted_dir / "page_0001.png").is_file()

    repeated_extract = runner.invoke(
        cli,
        [
            "pdf",
            "extract",
            str(first_pdf),
            "--output",
            str(extracted_dir),
            "--pages",
            "1",
            "--json",
        ],
    )
    assert repeated_extract.exit_code == 0, repeated_extract.output
    repeated_payload = json.loads(repeated_extract.output)
    assert repeated_payload["exported_pages"] == 0
    assert repeated_payload["skipped_existing"] == 1

    second_pdf = tmp_path / "second.pdf"
    document = fitz.open()
    document.new_page(width=100, height=100)
    document.save(second_pdf)
    document.close()

    output = tmp_path / "combined.pdf"
    stale = fitz.open()
    stale.new_page()
    stale.save(output)
    stale.close()
    concatenated = runner.invoke(
        cli,
        [
            "pdf",
            "concat",
            str(first_pdf),
            str(second_pdf),
            "--output",
            str(output),
            "--overwrite",
            "--json",
        ],
    )
    assert concatenated.exit_code == 0, concatenated.output
    concat_payload = json.loads(concatenated.output)
    assert concat_payload["input_count"] == 2
    assert concat_payload["ignored_generated"] == 0
    assert concat_payload["page_count"] == 3

    compressed = tmp_path / "compressed.pdf"
    compression = runner.invoke(
        cli,
        [
            "pdf",
            "compress",
            str(output),
            "--output",
            str(compressed),
            "--preset",
            "lossless",
            "--json",
        ],
    )
    assert compression.exit_code == 0, compression.output
    assert json.loads(compression.output)["page_count"] == 3
    assert compressed.is_file()
