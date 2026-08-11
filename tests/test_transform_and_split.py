"""Tests for resize, rotate, and pdf split commands."""

import json

from click.testing import CliRunner
from PIL import Image

from pixshift.cli import cli


def _payload(result):
    return json.loads(result.output.strip())


def _make_image(path, size=(120, 80), mode="RGB", color=(10, 90, 200), fmt="PNG"):
    Image.new(mode, size, color).save(path, format=fmt)


def test_resize_percent_keeps_format_and_is_idempotent(tmp_path):
    src = tmp_path / "photo.png"
    _make_image(src, size=(200, 100))

    runner = CliRunner()
    first = runner.invoke(cli, ["resize", str(src), "--percent", "50", "--json"])
    assert first.exit_code == 0, first.output
    payload = _payload(first)
    assert payload["ok"] is True
    assert payload["success"] == 1

    out = tmp_path / "photo_resized.png"
    assert out.is_file()
    with Image.open(out) as image:
        assert image.size == (100, 50)
        assert image.format == "PNG"

    second = runner.invoke(cli, ["resize", str(src), "--percent", "50", "--json"])
    second_payload = _payload(second)
    assert second_payload["skipped"] == 1
    assert second_payload["success"] == 0


def test_resize_exact_size_and_max_size(tmp_path):
    src = tmp_path / "img.jpg"
    _make_image(src, size=(400, 300), fmt="JPEG")

    runner = CliRunner()
    exact = runner.invoke(
        cli, ["resize", str(src), "--size", "200x120", "-o", str(tmp_path / "a"), "--json"]
    )
    assert exact.exit_code == 0, exact.output
    with Image.open(tmp_path / "a" / "img_resized.jpg") as image:
        assert image.size == (200, 120)

    bounded = runner.invoke(
        cli, ["resize", str(src), "--max-size", "100", "-o", str(tmp_path / "b"), "--json"]
    )
    assert bounded.exit_code == 0, bounded.output
    with Image.open(tmp_path / "b" / "img_resized.jpg") as image:
        assert max(image.size) == 100


def test_resize_requires_exactly_one_mode(tmp_path):
    src = tmp_path / "img.png"
    _make_image(src)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["resize", str(src), "--percent", "50", "--max-size", "100", "--json"]
    )
    assert result.exit_code == 1
    assert _payload(result)["error"] == "conflicting_options"

    none_given = runner.invoke(cli, ["resize", str(src), "--json"])
    assert none_given.exit_code == 1
    assert _payload(none_given)["error"] == "conflicting_options"


def test_resize_dry_run_writes_nothing(tmp_path):
    src = tmp_path / "img.png"
    _make_image(src)
    runner = CliRunner()
    result = runner.invoke(cli, ["resize", str(src), "--percent", "50", "--dry-run", "--json"])
    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["mode"] == "dry_run"
    assert not (tmp_path / "img_resized.png").exists()


def test_rotate_90_swaps_dimensions(tmp_path):
    src = tmp_path / "img.png"
    _make_image(src, size=(120, 80))

    runner = CliRunner()
    result = runner.invoke(cli, ["rotate", str(src), "--degrees", "90", "--json"])
    assert result.exit_code == 0, result.output
    payload = _payload(result)
    assert payload["ok"] is True
    with Image.open(tmp_path / "img_rotated.png") as image:
        assert image.size == (80, 120)


def test_rotate_flip_preserves_dimensions_and_pixels_move(tmp_path):
    src = tmp_path / "img.png"
    image = Image.new("RGB", (2, 1))
    image.putpixel((0, 0), (255, 0, 0))
    image.putpixel((1, 0), (0, 0, 255))
    image.save(src, format="PNG")

    runner = CliRunner()
    result = runner.invoke(cli, ["rotate", str(src), "--flip", "horizontal", "--json"])
    assert result.exit_code == 0, result.output
    with Image.open(tmp_path / "img_rotated.png") as flipped:
        assert flipped.size == (2, 1)
        assert flipped.getpixel((0, 0)) == (0, 0, 255)
        assert flipped.getpixel((1, 0)) == (255, 0, 0)


def test_rotate_requires_an_operation(tmp_path):
    src = tmp_path / "img.png"
    _make_image(src)
    runner = CliRunner()
    result = runner.invoke(cli, ["rotate", str(src), "--json"])
    assert result.exit_code == 1
    assert _payload(result)["error"] == "nothing_to_do"


def test_rotate_rejects_animated_input(tmp_path):
    src = tmp_path / "anim.gif"
    frames = [Image.new("RGB", (16, 16), color) for color in [(255, 0, 0), (0, 255, 0)]]
    frames[0].save(src, format="GIF", save_all=True, append_images=frames[1:], duration=100)

    runner = CliRunner()
    result = runner.invoke(cli, ["rotate", str(src), "--degrees", "90", "--json"])
    assert result.exit_code == 1
    payload = _payload(result)
    assert "animated_input_not_supported" in payload["errors"][0]


def _make_pdf(tmp_path, pages=3):
    src_dir = tmp_path / "pages"
    src_dir.mkdir()
    for index in range(pages):
        _make_image(src_dir / f"p{index}.png", size=(60, 40), color=(index * 40, 10, 10))
    pdf_path = tmp_path / "doc.pdf"
    runner = CliRunner()
    result = runner.invoke(cli, ["pdf", "merge", str(src_dir), "-o", str(pdf_path), "--json"])
    assert result.exit_code == 0, result.output
    return pdf_path


def test_pdf_split_each_page(tmp_path):
    pdf_path = _make_pdf(tmp_path, pages=3)
    out_dir = tmp_path / "split"

    runner = CliRunner()
    result = runner.invoke(cli, ["pdf", "split", str(pdf_path), "-o", str(out_dir), "--json"])
    assert result.exit_code == 0, result.output
    payload = _payload(result)
    assert payload["command"] == "pdf.split"
    assert payload["ok"] is True
    assert payload["written_files"] == 3
    assert sorted(p.name for p in out_dir.glob("*.pdf")) == [
        "doc_page_0001.pdf",
        "doc_page_0002.pdf",
        "doc_page_0003.pdf",
    ]


def test_pdf_split_page_subset_single_document(tmp_path):
    pdf_path = _make_pdf(tmp_path, pages=3)
    out_dir = tmp_path / "split"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["pdf", "split", str(pdf_path), "-o", str(out_dir), "--pages", "1,3", "--single", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = _payload(result)
    assert payload["written_files"] == 1
    outputs = list(out_dir.glob("*.pdf"))
    assert len(outputs) == 1

    info = runner.invoke(cli, ["pdf", "info", str(outputs[0]), "--json"])
    assert _payload(info)["page_count"] == 2


def test_pdf_split_skips_existing_outputs(tmp_path):
    pdf_path = _make_pdf(tmp_path, pages=2)
    out_dir = tmp_path / "split"

    runner = CliRunner()
    first = runner.invoke(cli, ["pdf", "split", str(pdf_path), "-o", str(out_dir), "--json"])
    assert first.exit_code == 0
    second = runner.invoke(cli, ["pdf", "split", str(pdf_path), "-o", str(out_dir), "--json"])
    assert second.exit_code == 0
    payload = _payload(second)
    assert payload["written_files"] == 0
    assert payload["skipped_existing"] == 2


def test_watch_command_is_removed():
    runner = CliRunner()
    root = runner.invoke(cli, [])
    assert "watch" not in root.output
    missing = runner.invoke(cli, ["watch", "--help"])
    assert missing.exit_code != 0
