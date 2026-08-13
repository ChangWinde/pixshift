"""Regression tests for the human-readable (no --json) command surfaces.

The machine interface is covered elsewhere; these lock the human tables
and exit codes so renderer changes cannot silently break the CLI.
"""

import json

from click.testing import CliRunner
from PIL import Image

from pixshift.cli import cli


def _make_image(path, size=(48, 32), color=(120, 30, 30)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format="PNG")
    return path


def _make_pdf(tmp_path, pages=2):
    src_dir = tmp_path / "pdf-pages"
    for index in range(pages):
        _make_image(src_dir / f"p{index}.png", color=(index * 60, 20, 20))
    pdf_path = tmp_path / "doc.pdf"
    result = CliRunner().invoke(cli, ["pdf", "merge", str(src_dir), "-o", str(pdf_path), "--json"])
    assert result.exit_code == 0, result.output
    return pdf_path


def test_tools_renders_the_catalog_table():
    result = CliRunner().invoke(cli, ["tools"])
    assert result.exit_code == 0, result.output
    assert "工具目录" in result.output
    assert "convert" in result.output


def test_apply_renders_the_step_table(tmp_path):
    src = _make_image(tmp_path / "in.png")
    plan = {"command": "convert", "input": str(src), "arguments": {"format": "webp"}}
    out_dir = tmp_path / "out"
    result = CliRunner().invoke(
        cli,
        ["apply", "--plan", "-", "--output", str(out_dir)],
        input=json.dumps(plan),
    )
    assert result.exit_code == 0, result.output
    assert "计划执行" in result.output


def test_apply_reports_failure_with_exit_one(tmp_path):
    plan = {
        "command": "convert",
        "input": str(tmp_path / "missing.png"),
        "arguments": {"format": "webp"},
    }
    result = CliRunner().invoke(cli, ["apply", "--plan", "-"], input=json.dumps(plan))
    assert result.exit_code == 1
    assert "计划执行" in result.output


def test_prep_renders_a_summary(tmp_path):
    src = _make_image(tmp_path / "raw.png")
    out_dir = tmp_path / "prepped"
    result = CliRunner().invoke(cli, ["prep", str(src), "-o", str(out_dir)])
    assert result.exit_code == 0, result.output


def test_manifest_renders_a_table(tmp_path):
    src = _make_image(tmp_path / "img.png")
    result = CliRunner().invoke(cli, ["manifest", str(src)])
    assert result.exit_code == 0, result.output


def test_hash_renders_a_table(tmp_path):
    src = _make_image(tmp_path / "img.png")
    result = CliRunner().invoke(cli, ["hash", str(src)])
    assert result.exit_code == 0, result.output


def test_pdf_merge_renders_a_summary(tmp_path):
    src_dir = tmp_path / "pages"
    for index in range(2):
        _make_image(src_dir / f"p{index}.png")
    out_pdf = tmp_path / "merged.pdf"
    result = CliRunner().invoke(cli, ["pdf", "merge", str(src_dir), "-o", str(out_pdf)])
    assert result.exit_code == 0, result.output
    assert out_pdf.is_file()


def test_pdf_info_renders_a_table(tmp_path):
    pdf_path = _make_pdf(tmp_path)
    result = CliRunner().invoke(cli, ["pdf", "info", str(pdf_path)])
    assert result.exit_code == 0, result.output


def test_pdf_split_renders_a_summary(tmp_path):
    pdf_path = _make_pdf(tmp_path)
    out_dir = tmp_path / "split-pages"
    result = CliRunner().invoke(cli, ["pdf", "split", str(pdf_path), "-o", str(out_dir)])
    assert result.exit_code == 0, result.output
    assert list(out_dir.glob("*.pdf"))


def test_compress_renders_a_result_table(tmp_path):
    src = _make_image(tmp_path / "big.png", size=(256, 256))
    out_dir = tmp_path / "compressed"
    result = CliRunner().invoke(cli, ["compress", str(src), "-o", str(out_dir)])
    assert result.exit_code == 0, result.output


def test_compress_dry_run_previews_without_writing(tmp_path):
    src = _make_image(tmp_path / "big.png", size=(256, 256))
    out_dir = tmp_path / "compressed"
    result = CliRunner().invoke(cli, ["compress", str(src), "-o", str(out_dir), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert not out_dir.exists() or not list(out_dir.iterdir())


def test_strip_renders_a_result_table(tmp_path):
    src = _make_image(tmp_path / "photo.png")
    out_dir = tmp_path / "clean"
    result = CliRunner().invoke(cli, ["strip", str(src), "-o", str(out_dir)])
    assert result.exit_code == 0, result.output


def test_dedup_reports_duplicates_without_deleting(tmp_path):
    src_dir = tmp_path / "dupes"
    _make_image(src_dir / "one.png", color=(50, 60, 70))
    _make_image(src_dir / "two.png", color=(50, 60, 70))
    result = CliRunner().invoke(cli, ["dedup", str(src_dir)])
    assert result.exit_code == 0, result.output
    assert (src_dir / "one.png").is_file()
    assert (src_dir / "two.png").is_file()


def test_resize_table_reports_truncation_and_summary(tmp_path):
    src_dir = tmp_path / "many"
    for index in range(55):
        _make_image(src_dir / f"img_{index:03d}.png")
    result = CliRunner().invoke(cli, ["resize", str(src_dir), "--percent", "50"])
    assert result.exit_code == 0, result.output
    assert "还有 5 个文件" in result.output
    assert "成功 55 · 跳过 0 · 失败 0" in result.output


def test_rotate_summary_counts_failures(tmp_path):
    src_dir = tmp_path / "mixed"
    _make_image(src_dir / "good.png")
    (src_dir / "broken.png").write_bytes(b"not a png")
    result = CliRunner().invoke(cli, ["rotate", str(src_dir), "--degrees", "90"])
    assert result.exit_code == 1
    assert "成功 1 · 跳过 0 · 失败 1" in result.output


def test_crop_lists_failed_files(tmp_path):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not a png")
    result = CliRunner().invoke(cli, ["crop", str(broken), "--crop", "1,1,10,10"])
    assert result.exit_code == 1
    assert "失败文件:" in result.output
    assert "broken.png" in result.output


def test_watermark_lists_failed_files(tmp_path):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not a png")
    result = CliRunner().invoke(cli, ["watermark", "text", str(broken), "--text", "pix"])
    assert result.exit_code == 1
    assert "失败文件:" in result.output
    assert "broken.png" in result.output
