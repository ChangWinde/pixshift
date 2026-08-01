"""Tests for advanced command JSON outputs."""

import json

from click.testing import CliRunner
from PIL import Image

from pixshift.cli import cli


def test_compare_json_output(tmp_path):
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    Image.new("RGB", (20, 20), (10, 10, 10)).save(a, format="PNG")
    Image.new("RGB", (20, 20), (10, 10, 12)).save(b, format="PNG")
    runner = CliRunner()
    result = runner.invoke(cli, ["compare", str(a), str(b), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output.strip())
    assert payload["command"] == "compare"
    assert payload["ok"] is True
    assert payload["comparison_size"] == [20, 20]


def test_compare_rejects_mismatched_aspect_ratios(tmp_path):
    a = tmp_path / "wide.png"
    b = tmp_path / "square.png"
    Image.new("RGB", (40, 20), "red").save(a, format="PNG")
    Image.new("RGB", (20, 20), "red").save(b, format="PNG")

    result = CliRunner().invoke(cli, ["compare", str(a), str(b), "--json"])

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["error"] == "aspect_ratio_mismatch"


def test_crop_json_dry_run(tmp_path):
    src = tmp_path / "img.png"
    Image.new("RGB", (40, 30), (100, 110, 120)).save(src, format="PNG")
    runner = CliRunner()
    result = runner.invoke(cli, ["crop", str(src), "--aspect", "1:1", "--dry-run", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output.strip())
    assert payload["command"] == "crop"
    assert payload["mode"] == "dry_run"


def test_watermark_text_json_dry_run(tmp_path):
    src = tmp_path / "img.png"
    Image.new("RGB", (32, 32), (100, 100, 100)).save(src, format="PNG")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["watermark", "text", str(src), "--text", "demo", "--dry-run", "--json"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output.strip())
    assert payload["command"] == "watermark.text"
    assert payload["mode"] == "dry_run"


def test_watermark_image_json_output(tmp_path):
    src = tmp_path / "img.png"
    logo = tmp_path / "logo.png"
    output = tmp_path / "output"
    Image.new("RGB", (64, 64), (100, 100, 100)).save(src, format="PNG")
    Image.new("RGBA", (8, 8), (255, 255, 255, 200)).save(logo, format="PNG")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "watermark",
            "image",
            str(src),
            "--watermark",
            str(logo),
            "--output",
            str(output),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip())
    assert payload["command"] == "watermark.image"
    assert payload["success"] == 1
    assert (output / "img_wm.png").is_file()


def test_montage_json_output(tmp_path):
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    out = tmp_path / "montage.png"
    Image.new("RGB", (20, 20), (1, 2, 3)).save(a, format="PNG")
    Image.new("RGB", (20, 20), (4, 5, 6)).save(b, format="PNG")
    runner = CliRunner()
    result = runner.invoke(cli, ["montage", str(tmp_path), "-o", str(out), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output.strip())
    assert payload["command"] == "montage"
    assert payload["ok"] is True
    assert payload["total_images"] >= 2


def test_optimize_json_output(tmp_path):
    src = tmp_path / "img.png"
    Image.new("RGB", (24, 24), (120, 20, 50)).save(src, format="PNG")
    runner = CliRunner()
    result = runner.invoke(cli, ["optimize", str(src), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output.strip())
    assert payload["command"] == "optimize"
    assert payload["total"] == 1
    item = payload["results"][0]
    assert item["analysis"]["dimensions"] == [24, 24]
    assert item["analysis"]["sampled"] is False
    assert item["estimates"]
    assert item["plan"] == {
        "command": "compress",
        "arguments": {"preset": "lossless"},
    }


def test_watch_json_once_output(tmp_path):
    src = tmp_path / "img.png"
    Image.new("RGB", (16, 16), (10, 20, 30)).save(src, format="PNG")
    out = tmp_path / "converted"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["watch", str(tmp_path), "--once", "--json", "-t", "jpg", "-o", str(out), "--overwrite"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output.strip())
    assert payload["command"] == "watch"
    assert payload["mode"] == "once"
    assert payload["ok"] is True
