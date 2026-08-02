"""Successful CLI journeys for every PDF transformation command."""

import json
from pathlib import Path

import fitz
from click.testing import CliRunner
from PIL import Image

from pixshift.cli import cli


def test_pdf_transform_workflow_and_concat_excludes_own_output(tmp_path: Path) -> None:
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
        ["pdf", "concat", str(tmp_path), "--output", str(output), "--overwrite", "--json"],
    )
    assert concatenated.exit_code == 0, concatenated.output
    concat_payload = json.loads(concatenated.output)
    assert concat_payload["input_count"] == 2
    assert concat_payload["ignored_generated"] == 1
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
