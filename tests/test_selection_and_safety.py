"""Tests for batch selection filters, the pixel budget, and reversible dedup."""

import io
import json
import os
import subprocess
import sys
import warnings
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image

from pixshift.cli import cli
from pixshift.core.errors import ImageTooLargeError
from pixshift.core.files import SelectionFilters, collect_supported_files
from pixshift.core.metadata import ensure_within_pixel_limit, max_image_pixels, open_image

IMAGE_EXTS = {".png", ".jpg", ".jpeg"}


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def tree(tmp_path):
    """A small tree: two large photos, one tiny photo, one in a thumbs/ subdir."""
    source = tmp_path / "src"
    (source / "thumbs").mkdir(parents=True)
    big = Image.new("RGB", (400, 300))
    big.putdata([(index % 255, 90, 30) for index in range(400 * 300)])
    big.save(source / "one.jpg", quality=95)
    big.save(source / "two.jpg", quality=95)
    Image.new("RGB", (8, 8), "red").save(source / "tiny.png")
    Image.new("RGB", (8, 8), "blue").save(source / "thumbs" / "t.png")
    return source


# ------------------------------------------------------------------
# Selection filters
# ------------------------------------------------------------------


def test_collector_applies_include_exclude_and_size(tree):
    everything = collect_supported_files([str(tree)], IMAGE_EXTS, recursive=True)
    assert len(everything) == 4

    only_jpg = collect_supported_files(
        [str(tree)], IMAGE_EXTS, recursive=True, selection=SelectionFilters(include=("*.jpg",))
    )
    assert {Path(path).name for path in only_jpg} == {"one.jpg", "two.jpg"}

    without_thumbs = collect_supported_files(
        [str(tree)], IMAGE_EXTS, recursive=True, selection=SelectionFilters(exclude=("*/thumbs/*",))
    )
    assert all("thumbs" not in path for path in without_thumbs)
    assert len(without_thumbs) == 3

    large_only = collect_supported_files(
        [str(tree)], IMAGE_EXTS, recursive=True, selection=SelectionFilters(min_bytes=2000)
    )
    assert {Path(path).name for path in large_only} == {"one.jpg", "two.jpg"}


def test_filters_apply_to_explicitly_named_files(tree):
    """Filters are an explicit request, so they narrow named files too."""
    named = [str(tree / "one.jpg"), str(tree / "tiny.png")]
    kept = collect_supported_files(
        named, IMAGE_EXTS, selection=SelectionFilters(include=("*.jpg",))
    )
    assert [Path(path).name for path in kept] == ["one.jpg"]


def test_inactive_filters_change_nothing(tree):
    baseline = collect_supported_files([str(tree)], IMAGE_EXTS, recursive=True)
    with_empty = collect_supported_files(
        [str(tree)], IMAGE_EXTS, recursive=True, selection=SelectionFilters()
    )
    assert baseline == with_empty


@pytest.mark.parametrize(
    "command",
    [
        ["compress"],
        ["convert", "-t", "webp"],
        ["strip"],
        ["resize", "--percent", "50"],
        ["rotate", "--degrees", "90"],
        ["crop", "--aspect", "1:1"],
        ["optimize"],
        ["manifest"],
        ["hash"],
    ],
    ids=lambda argv: argv[0],
)
def test_every_batch_command_accepts_the_shared_filters(runner, tree, tmp_path, command):
    """The filter vocabulary must be identical across the batch surface."""
    argv = [*command, str(tree), "-r", "--exclude", "*/thumbs/*", "--json"]
    if command[0] not in {"optimize", "manifest", "hash"}:
        argv += ["-o", str(tmp_path / f"out_{command[0]}")]
    result = runner.invoke(cli, argv)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    counted = payload.get("total", payload.get("total_files", 0))
    assert counted == 3, f"{command[0]} did not apply --exclude: {payload}"


def test_malformed_min_file_size_is_a_usage_error(runner, tree):
    result = runner.invoke(cli, ["compress", str(tree), "--min-file-size", "huge", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.output)["error"] == "invalid_min_file_size"


# ------------------------------------------------------------------
# Decompression-bomb budget
# ------------------------------------------------------------------


class _Canvas:
    def __init__(self, width, height):
        self.size = (width, height)


def test_pixel_budget_rejects_a_bomb_and_accepts_real_photos():
    ensure_within_pixel_limit(_Canvas(11648, 8736))  # 102MP medium format
    with pytest.raises(ImageTooLargeError) as excinfo:
        ensure_within_pixel_limit(_Canvas(40000, 40000))  # 1.6 gigapixels
    assert str(excinfo.value).startswith("image_too_large:")


def test_pixel_budget_is_configurable(monkeypatch):
    monkeypatch.setenv("PIXSHIFT_MAX_PIXELS", "100")
    assert max_image_pixels() == 100
    with pytest.raises(ImageTooLargeError):
        ensure_within_pixel_limit(_Canvas(20, 20))

    monkeypatch.setenv("PIXSHIFT_MAX_PIXELS", "0")
    ensure_within_pixel_limit(_Canvas(40000, 40000))  # disabled

    monkeypatch.setenv("PIXSHIFT_MAX_PIXELS", "not-a-number")
    assert max_image_pixels() > 0  # falls back to the default rather than crashing


def test_oversized_image_reports_a_stable_error(runner, tmp_path, monkeypatch):
    source = tmp_path / "wide.png"
    Image.new("RGB", (64, 64), "green").save(source)
    monkeypatch.setenv("PIXSHIFT_MAX_PIXELS", "100")
    result = runner.invoke(cli, ["compress", str(source), "-o", str(tmp_path / "o"), "--json"])
    assert result.exit_code == 1
    assert "image_too_large" in json.loads(result.output)["errors"][0]["error"]


def test_pixel_budget_guards_info_without_polluting_json(runner, tmp_path, monkeypatch):
    """The shared Image.open guard must cover paths without an explicit check."""
    source = tmp_path / "wide.png"
    Image.new("RGB", (64, 64), "green").save(source)
    monkeypatch.setenv("PIXSHIFT_MAX_PIXELS", "100")

    rejected = runner.invoke(cli, ["info", str(source), "--json"])

    assert rejected.exit_code == 1
    assert rejected.stderr == ""
    rejected_payload = json.loads(rejected.stdout)
    assert rejected_payload["ok"] is False
    assert rejected_payload["files"][0]["error"] == "image_too_large:4096>100"

    monkeypatch.setenv("PIXSHIFT_MAX_PIXELS", "0")
    accepted = runner.invoke(cli, ["info", str(source), "--json"])
    assert accepted.exit_code == 0
    assert json.loads(accepted.stdout)["ok"] is True


def test_import_does_not_replace_the_host_pillow_policy():
    script = """
from PIL import Image
Image.MAX_IMAGE_PIXELS = 100
original_open = Image.open
import pixshift
assert Image.MAX_IMAGE_PIXELS == 100
assert Image.open is original_open
"""
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr


def test_open_image_does_not_suppress_host_pillow_warnings(tmp_path, monkeypatch):
    source = tmp_path / "host-policy.png"
    Image.new("RGB", (11, 10), "green").save(source)
    monkeypatch.setenv("PIXSHIFT_MAX_PIXELS", "0")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", Image.DecompressionBombWarning)
        with open_image(source):
            pass

    assert any(item.category is Image.DecompressionBombWarning for item in caught)


def test_open_image_preserves_host_warning_threshold_as_error(tmp_path, monkeypatch):
    source = tmp_path / "host-policy.png"
    Image.new("RGB", (11, 10), "green").save(source)
    monkeypatch.setenv("PIXSHIFT_MAX_PIXELS", "0")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)

    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with pytest.raises(ImageTooLargeError, match=r"image_too_large:110>100"):
            open_image(source)


def test_open_image_does_not_close_a_caller_owned_stream(monkeypatch):
    stream = io.BytesIO()
    Image.new("RGB", (16, 16), "green").save(stream, format="PNG")
    stream.seek(0)
    monkeypatch.setenv("PIXSHIFT_MAX_PIXELS", "100")

    with pytest.raises(ImageTooLargeError):
        open_image(stream)

    assert stream.closed is False


def test_open_image_cleanup_cannot_mask_the_policy_error(monkeypatch):
    class BrokenCloseImage:
        size = (16, 16)

        def close(self):
            raise RuntimeError("plugin_close_failed")

    monkeypatch.setattr(Image, "open", lambda path: BrokenCloseImage())
    monkeypatch.setenv("PIXSHIFT_MAX_PIXELS", "100")

    with pytest.raises(ImageTooLargeError, match=r"image_too_large:256>100"):
        open_image("broken.plugin")


def test_budget_can_be_enabled_after_startup_with_zero(tmp_path):
    source = tmp_path / "wide.png"
    Image.new("RGB", (64, 64), "green").save(source)
    script = f"""
import json, os
from click.testing import CliRunner
from pixshift.cli import cli
os.environ['PIXSHIFT_MAX_PIXELS'] = '100'
result = CliRunner().invoke(cli, ['info', {str(source)!r}, '--json'])
assert result.exit_code == 1, result.output
assert json.loads(result.stdout)['files'][0]['error'] == 'image_too_large:4096>100'
"""
    environment = dict(os.environ)
    environment["PIXSHIFT_MAX_PIXELS"] = "0"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr


def test_animation_checks_every_frame_before_copying(runner, tmp_path, monkeypatch):
    source = tmp_path / "frames.tiff"
    first = Image.new("RGB", (8, 8), "green")
    second = Image.new("RGB", (64, 64), "blue")
    first.save(source, save_all=True, append_images=[second])
    monkeypatch.setenv("PIXSHIFT_MAX_PIXELS", "100")

    result = runner.invoke(
        cli, ["convert", str(source), "--to", "webp", "--output", str(tmp_path / "out"), "--json"]
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout)["errors"][0]["error"] == "image_too_large:4096>100"


def test_animation_enforces_an_aggregate_frame_budget(runner, tmp_path, monkeypatch):
    source = tmp_path / "many-frames.tiff"
    first = Image.new("RGB", (8, 8), "green")
    second = Image.new("RGB", (8, 8), "blue")
    first.save(source, save_all=True, append_images=[second])
    monkeypatch.setenv("PIXSHIFT_MAX_PIXELS", "100")

    result = runner.invoke(
        cli, ["convert", str(source), "--to", "webp", "--output", str(tmp_path / "out"), "--json"]
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout)["errors"][0]["error"] == "image_too_large:128>100"


# ------------------------------------------------------------------
# Reversible deduplication
# ------------------------------------------------------------------


def test_dedup_backup_dir_moves_instead_of_deleting(runner, tmp_path):
    source = tmp_path / "dupes"
    source.mkdir()
    image = Image.new("RGB", (32, 32), "teal")
    image.save(source / "a.png")
    image.save(source / "b.png")
    backup = tmp_path / "backup"

    result = runner.invoke(
        cli,
        [
            "dedup",
            str(source),
            "--threshold",
            "0",
            "--delete",
            "--yes",
            "--backup-dir",
            str(backup),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    survivors = sorted(path.name for path in source.iterdir())
    moved = sorted(path.name for path in backup.iterdir())
    assert len(survivors) == 1
    assert len(moved) == 1
    # Nothing was destroyed: the duplicate still exists, just relocated.
    assert (backup / moved[0]).stat().st_size > 0


def test_dedup_backup_dir_avoids_name_collisions(tmp_path):
    from pixshift.dedup_engine import _backup_destination

    backup = tmp_path / "b"
    backup.mkdir()
    (backup / "photo.jpg").write_bytes(b"first")
    destination = _backup_destination("/elsewhere/photo.jpg", str(backup))
    assert destination.name == "photo_1.jpg"
