"""Tests for machine-readable JSON command outputs."""

import json

import pytest
from click.testing import CliRunner
from PIL import Image

from pixshift.cli import cli


def test_compress_json_output(tmp_path):
    src = tmp_path / "img.jpg"
    Image.new("RGB", (32, 32), (120, 20, 20)).save(src, format="JPEG")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["compress", str(src), "--json", "--output", str(tmp_path / "out"), "--overwrite"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output.strip())
    assert payload["command"] == "compress"
    assert payload["total"] == 1
    assert "duration_sec" in payload


def test_convert_json_output(tmp_path):
    src = tmp_path / "img.png"
    Image.new("RGB", (20, 20), (10, 120, 30)).save(src, format="PNG")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "convert",
            str(src),
            "-t",
            "jpg",
            "--json",
            "--output",
            str(tmp_path / "out"),
            "--overwrite",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output.strip())
    assert payload["command"] == "convert"
    assert payload["total"] == 1
    assert payload["output_format"] == "jpg"


def test_convert_json_invalid_resize_exit_code(tmp_path):
    src = tmp_path / "img.png"
    Image.new("RGB", (20, 20), (40, 50, 60)).save(src, format="PNG")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["convert", str(src), "-t", "jpg", "--resize", "bad", "--json"],
    )
    assert result.exit_code == 1
    payload = json.loads(result.output.strip())
    assert payload["command"] == "convert"
    assert payload["ok"] is False
    assert payload["error"] == "invalid_resize"


def test_strip_json_dry_run(tmp_path):
    src = tmp_path / "img.png"
    Image.new("RGB", (16, 16), (10, 10, 10)).save(src, format="PNG")

    runner = CliRunner()
    result = runner.invoke(cli, ["strip", str(src), "--dry-run", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output.strip())
    assert payload["command"] == "strip"
    assert payload["mode"] == "dry_run"
    assert payload["total"] == 1
    assert isinstance(payload["preview"], list)


def test_dedup_json_analyze(tmp_path):
    img_a = tmp_path / "a.jpg"
    img_b = tmp_path / "b.jpg"
    image = Image.new("RGB", (24, 24), (200, 200, 200))
    image.save(img_a, format="JPEG")
    image.save(img_b, format="JPEG")

    runner = CliRunner()
    result = runner.invoke(cli, ["dedup", str(tmp_path), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output.strip())
    assert payload["command"] == "dedup"
    assert payload["mode"] == "analyze"
    assert "duplicate_groups" in payload
    assert "recoverable_bytes" in payload


def test_dedup_json_delete_cancelled_exit_code(tmp_path):
    img_a = tmp_path / "a.jpg"
    img_b = tmp_path / "b.jpg"
    image = Image.new("RGB", (24, 24), (123, 123, 123))
    image.save(img_a, format="JPEG")
    image.save(img_b, format="JPEG")

    runner = CliRunner()
    result = runner.invoke(cli, ["dedup", str(tmp_path), "--delete", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output.strip())
    assert payload["command"] == "dedup"
    assert payload["ok"] is False
    assert payload["message"] == "confirmation_required"


def test_dedup_json_delete_dry_run(tmp_path):
    img_a = tmp_path / "a.jpg"
    img_b = tmp_path / "b.jpg"
    image = Image.new("RGB", (24, 24), (222, 222, 222))
    image.save(img_a, format="JPEG")
    image.save(img_b, format="JPEG")

    runner = CliRunner()
    result = runner.invoke(cli, ["dedup", str(tmp_path), "--delete", "--dry-run", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output.strip())
    assert payload["command"] == "dedup"
    assert payload["mode"] == "delete_dry_run"
    assert payload["ok"] is True


def test_pdf_info_json_output(tmp_path):
    fitz = pytest.importorskip("fitz")
    pdf_path = tmp_path / "doc.pdf"
    doc = fitz.open()
    doc.new_page(width=200, height=200)
    doc.save(str(pdf_path))
    doc.close()

    runner = CliRunner()
    result = runner.invoke(cli, ["pdf", "info", str(pdf_path), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output.strip())
    assert payload["command"] == "pdf.info"
    assert payload["ok"] is True
    assert payload["page_count"] == 1


def test_info_json_output(tmp_path):
    src = tmp_path / "img.png"
    Image.new("RGB", (12, 12), (9, 9, 9)).save(src, format="PNG")
    runner = CliRunner()
    result = runner.invoke(cli, ["info", str(src), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output.strip())
    assert payload["command"] == "info"
    assert payload["ok"] is True
    assert payload["total"] == 1
    assert isinstance(payload["files"], list)


def test_formats_json_output():
    runner = CliRunner()
    result = runner.invoke(cli, ["formats", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output.strip())
    assert payload["command"] == "formats"
    assert payload["ok"] is True
    assert "input_extensions" in payload
    assert "output_formats" in payload


def test_doctor_json_output():
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output.strip())
    assert payload["command"] == "doctor"
    assert payload["ok"] is True
    assert isinstance(payload["all_ready"], bool)
    assert isinstance(payload["checks"], list)

