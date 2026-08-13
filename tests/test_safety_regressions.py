"""End-to-end regressions for safety and public contract failures."""

import json
import random
import shutil
from importlib.metadata import version
from pathlib import Path

import fitz
from click.testing import CliRunner
from PIL import Image, ImageOps

from pixshift import __version__
from pixshift.cli import cli
from pixshift.compare_engine import compare_images
from pixshift.compress_engine import compress_single
from pixshift.converter import SUPPORTED_OUTPUT_FORMATS, PixShiftConverter
from pixshift.crop_engine import crop_single
from pixshift.dedup_engine import _cluster_by_hash, delete_duplicates, find_duplicates
from pixshift.montage_engine import create_montage
from pixshift.optimize_engine import analyze_image
from pixshift.watermark_engine import add_text_watermark


def _oriented_jpeg(path: Path) -> None:
    image = Image.new("RGB", (2, 3), "black")
    image.putpixel((0, 0), (255, 0, 0))
    exif = Image.Exif()
    exif[274] = 6
    image.save(path, format="JPEG", exif=exif)


def test_runtime_version_matches_package_metadata() -> None:
    assert __version__ == version("pixshift")


def test_convert_normalizes_exif_orientation(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    output = tmp_path / "output.jpg"
    _oriented_jpeg(source)

    result = PixShiftConverter(overwrite=True).convert_single(str(source), str(output))

    assert result.success is True
    with Image.open(output) as converted:
        assert converted.size == (3, 2)
        assert converted.getexif().get(274) in (None, 1)
        assert ImageOps.exif_transpose(converted).size == (3, 2)


def test_convert_preserves_orientation_when_auto_orient_is_disabled(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    output = tmp_path / "output.jpg"
    _oriented_jpeg(source)

    result = PixShiftConverter(auto_orient=False, overwrite=True).convert_single(
        str(source), str(output)
    )

    assert result.success is True
    with Image.open(output) as converted:
        assert converted.size == (2, 3)
        assert converted.getexif().get(274) == 6
        assert ImageOps.exif_transpose(converted).size == (3, 2)


def test_convert_to_ico_preserves_alpha(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.ico"
    image = Image.new("RGBA", (32, 32), (255, 0, 0, 255))
    image.putpixel((0, 0), (0, 0, 0, 0))
    image.save(source)

    result = PixShiftConverter(overwrite=True).convert_single(str(source), str(output))

    assert result.success is True, result.error
    with Image.open(output) as converted:
        assert converted.convert("RGBA").getpixel((0, 0))[3] == 0


def test_montage_rejects_mismatched_output_extension(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "montage.tiff"
    Image.new("RGB", (16, 16), "red").save(source)

    result = create_montage([str(source)], str(output), overwrite=True)

    assert result.success is False
    assert "unsupported_output_format" in result.error
    assert not output.exists()


def test_strip_privacy_normalizes_exif_orientation(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    output = tmp_path / "source_clean.jpg"
    _oriented_jpeg(source)

    result = CliRunner().invoke(
        cli,
        [
            "strip",
            str(source),
            "--mode",
            "privacy",
            "--output",
            str(tmp_path),
            "--overwrite",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    with Image.open(output) as cleaned:
        assert cleaned.size == (3, 2)
        assert cleaned.getexif().get(274) in (None, 1)
        assert ImageOps.exif_transpose(cleaned).size == (3, 2)


def test_advanced_image_operations_normalize_exif_orientation(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    _oriented_jpeg(source)

    crop_output = tmp_path / "crop.jpg"
    crop_result = crop_single(str(source), str(crop_output), trim=True, overwrite=True)
    assert crop_result.success is True, crop_result.error

    watermark_output = tmp_path / "watermark.jpg"
    watermark_result = add_text_watermark(str(source), str(watermark_output), "x", overwrite=True)
    assert watermark_result.success is True, watermark_result.error

    montage_output = tmp_path / "montage.png"
    montage_result = create_montage(
        [str(source)], str(montage_output), cols=1, gap=0, overwrite=True
    )
    assert montage_result.success is True, montage_result.error

    for output in (crop_output, watermark_output, montage_output):
        with Image.open(output) as image:
            assert image.size == (3, 2)
            assert image.getexif().get(274) in (None, 1)


def test_dedup_delete_never_removes_perceptually_similar_files(tmp_path: Path) -> None:
    for name, color in (
        ("red.png", (255, 0, 0)),
        ("blue.png", (0, 0, 255)),
        ("black.png", (0, 0, 0)),
    ):
        Image.new("RGB", (64, 64), color).save(tmp_path / name)

    result = CliRunner().invoke(
        cli, ["dedup", str(tmp_path), "--threshold", "0", "--delete", "--yes", "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["deleted"] == 0
    assert payload["deletable_files"] == 0
    assert sorted(path.name for path in tmp_path.glob("*.png")) == [
        "black.png",
        "blue.png",
        "red.png",
    ]


def test_dedup_delete_removes_only_exact_copy(tmp_path: Path) -> None:
    original = tmp_path / "a.png"
    duplicate = tmp_path / "b.png"
    different = tmp_path / "c.png"
    Image.new("RGB", (64, 64), (1, 2, 3)).save(original)
    shutil.copyfile(original, duplicate)
    Image.new("RGB", (64, 64), (4, 5, 6)).save(different)

    result = CliRunner().invoke(
        cli, ["dedup", str(tmp_path), "--threshold", "0", "--delete", "--yes", "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["deleted"] == 1
    assert payload["deletable_files"] == 1
    assert different.exists()
    assert sum(path.exists() for path in (original, duplicate)) == 1


def test_dedup_revalidates_candidate_before_delete(tmp_path: Path) -> None:
    original = tmp_path / "a.png"
    duplicate = tmp_path / "b.png"
    Image.new("RGB", (32, 32), "red").save(original)
    shutil.copyfile(original, duplicate)
    analysis = find_duplicates([str(tmp_path)], threshold=0)
    changed = bytearray(duplicate.read_bytes())
    changed[-1] ^= 1
    duplicate.write_bytes(changed)

    outcome = delete_duplicates(analysis.delete_candidates, dry_run=False)

    assert outcome["deleted"] == []
    assert outcome["skipped"]
    assert duplicate.exists()


def test_indexed_clustering_matches_brute_force_components() -> None:
    randomizer = random.Random(42)
    items = [(str(index), randomizer.getrandbits(64), index) for index in range(250)]
    threshold = 5

    actual = _cluster_by_hash(items, threshold)
    parents = list(range(len(items)))

    def find(index: int) -> int:
        while parents[index] != index:
            index = parents[index]
        return index

    for left in range(len(items)):
        for right in range(left):
            if (items[left][1] ^ items[right][1]).bit_count() <= threshold:
                parents[find(left)] = find(right)

    expected: dict[int, set[str]] = {}
    for index, item in enumerate(items):
        expected.setdefault(find(index), set()).add(item[0])

    assert {frozenset(item[0] for item in group) for group in actual} == {
        frozenset(group) for group in expected.values()
    }


def test_convert_rejects_prefix_path_traversal(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output_dir = tmp_path / "output"
    Image.new("RGB", (4, 4), "red").save(source)

    result = CliRunner().invoke(
        cli,
        [
            "convert",
            str(source),
            "--to",
            "jpg",
            "--output",
            str(output_dir),
            "--prefix",
            "../escaped_",
            "--json",
        ],
    )

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"] == "invalid_filename_component"
    assert not (tmp_path / "escaped_source.jpg").exists()


def test_pdf_extract_rejects_prefix_path_traversal(tmp_path: Path) -> None:
    source = tmp_path / "one.pdf"
    output_dir = tmp_path / "pages"
    document = fitz.open()
    document.new_page()
    document.save(source)
    document.close()

    result = CliRunner().invoke(
        cli,
        [
            "pdf",
            "extract",
            str(source),
            "--output",
            str(output_dir),
            "--prefix",
            "../escaped_",
            "--json",
        ],
    )

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"] == "invalid_filename_component"
    assert not (tmp_path / "escaped_page_0001.png").exists()


def test_flatten_collision_fails_before_writing(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    output = tmp_path / "output"
    first.mkdir()
    second.mkdir()
    Image.new("RGB", (8, 8), "red").save(first / "same.png")
    Image.new("RGB", (8, 8), "blue").save(second / "same.png")

    result = CliRunner().invoke(
        cli,
        [
            "crop",
            str(first),
            str(second),
            "--aspect",
            "1:1",
            "--output",
            str(output),
            "--flatten",
            "--overwrite",
            "--json",
        ],
    )

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"] == "output_collision"
    assert not output.exists()


def test_failed_overwrite_preserves_existing_output(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.png"
    Image.new("RGB", (8, 8), "red").save(source)
    output.write_bytes(b"existing-output")

    def broken_save(_self, path, **_kwargs):
        Path(path).write_bytes(b"partial")
        raise OSError("simulated encoder failure")

    monkeypatch.setattr("PIL.Image.Image.save", broken_save)
    result = PixShiftConverter(overwrite=True).convert_single(str(source), str(output))

    assert result.success is False
    assert output.read_bytes() == b"existing-output"


def test_crop_failed_overwrite_preserves_existing_output(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.png"
    Image.new("RGB", (8, 8), "red").save(source)
    output.write_bytes(b"existing-output")

    def broken_save(_self, path, **_kwargs):
        Path(path).write_bytes(b"partial")
        raise OSError("simulated encoder failure")

    monkeypatch.setattr("PIL.Image.Image.save", broken_save)
    result = crop_single(str(source), str(output), trim=True, overwrite=True)

    assert result.success is False
    assert output.read_bytes() == b"existing-output"


def test_target_size_unreachable_is_failure(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    output = tmp_path / "output.jpg"
    Image.effect_noise((256, 256), 100).convert("RGB").save(source, format="JPEG")

    result = compress_single(str(source), str(output), target_size="1B", overwrite=True)

    assert result.success is False
    assert "target_size_unreachable" in result.error
    assert not output.exists()


def test_target_size_success_respects_bound(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    output = tmp_path / "output.jpg"
    Image.effect_noise((256, 256), 100).convert("RGB").save(source, format="JPEG")

    result = compress_single(str(source), str(output), target_size="24KB", overwrite=True)

    assert result.success is True, result.error
    assert 0 < result.output_size <= 24 * 1024


def test_lossless_preset_is_byte_identical_for_jpeg(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    output = tmp_path / "output.jpg"
    Image.effect_noise((64, 64), 100).convert("RGB").save(source, format="JPEG")

    result = compress_single(str(source), str(output), preset="lossless", overwrite=True)

    assert result.success is True, result.error
    assert output.read_bytes() == source.read_bytes()


def test_analysis_uses_visual_orientation(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    visual = tmp_path / "visual.png"
    _oriented_jpeg(source)
    with Image.open(source) as opened:
        ImageOps.exif_transpose(opened).save(visual)

    comparison = compare_images(str(source), str(visual))
    optimization = analyze_image(str(source))

    assert comparison.success is True, comparison.error
    assert comparison.size_a == comparison.size_b == (3, 2)
    assert comparison.mse == 0
    assert (optimization.width, optimization.height) == (3, 2)


def test_json_info_and_optimize_fail_with_nonzero_exit(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.jpg"
    invalid.write_bytes(b"not-an-image")
    runner = CliRunner()

    for argv in (["info", str(invalid), "--json"], ["optimize", str(invalid), "--json"]):
        result = runner.invoke(cli, argv)
        assert result.exit_code != 0, argv
        payload = json.loads(result.output)
        assert payload["ok"] is False


def test_human_mode_failures_return_nonzero_exit(tmp_path: Path) -> None:
    invalid_image = tmp_path / "invalid.jpg"
    valid_image = tmp_path / "valid.png"
    invalid_image.write_bytes(b"not-an-image")
    Image.new("RGB", (4, 4), "red").save(valid_image)
    runner = CliRunner()

    commands = (
        ["info", str(invalid_image)],
        ["compare", str(invalid_image), str(valid_image)],
        ["convert", str(invalid_image), "--to", "png"],
    )
    for command in commands:
        result = runner.invoke(cli, command)
        assert result.exit_code != 0, command


def test_json_pdf_info_failure_is_structured(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.pdf"
    invalid.write_bytes(b"not-a-pdf")

    result = CliRunner().invoke(cli, ["pdf", "info", str(invalid), "--json"])

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["command"] == "pdf.info"
    assert payload["ok"] is False
    assert payload["error"]


def test_runtime_output_formats_exclude_unavailable_handlers() -> None:
    assert "bufr" not in SUPPORTED_OUTPUT_FORMATS
    assert "grib" not in SUPPORTED_OUTPUT_FORMATS
    assert "hdf5" not in SUPPORTED_OUTPUT_FORMATS
    assert "wmf" not in SUPPORTED_OUTPUT_FORMATS


def test_runtime_input_formats_exclude_save_only_and_stub_handlers() -> None:
    from pixshift.converter import SUPPORTED_INPUT_FORMATS

    assert ".pdf" not in SUPPORTED_INPUT_FORMATS
    assert ".bufr" not in SUPPORTED_INPUT_FORMATS
    assert ".grib" not in SUPPORTED_INPUT_FORMATS
    assert ".h5" not in SUPPORTED_INPUT_FORMATS
    assert ".mpeg" not in SUPPORTED_INPUT_FORMATS


def test_doctor_json_fails_only_for_required_checks(monkeypatch) -> None:
    monkeypatch.setattr(
        "pixshift.commands.system_commands._collect_doctor_checks",
        lambda: [("required", "missing", False, True), ("optional", "missing", False, False)],
    )

    failed = CliRunner().invoke(cli, ["doctor", "--json"])

    assert failed.exit_code != 0
    failed_payload = json.loads(failed.output)
    assert failed_payload["ok"] is False
    assert failed_payload["all_ready"] is False
    assert failed_payload["checks"][0]["required"] is True

    monkeypatch.setattr(
        "pixshift.commands.system_commands._collect_doctor_checks",
        lambda: [("optional", "missing", False, False)],
    )
    optional_only = CliRunner().invoke(cli, ["doctor", "--json"])

    assert optional_only.exit_code == 0
    assert json.loads(optional_only.output)["ok"] is True


def test_json_contract_has_schema_version(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (4, 4), "red").save(source)

    result = CliRunner().invoke(cli, ["info", str(source), "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["schema_version"] == "1.1"


def test_json_mode_serializes_click_validation_errors(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (4, 4), "red").save(source)
    runner = CliRunner()

    invalid_value = runner.invoke(
        cli,
        ["convert", str(source), "--to", "not-a-format", "--json"],
    )
    unknown_option = runner.invoke(cli, ["info", str(source), "--unknown", "--json"])

    for result in (invalid_value, unknown_option):
        assert result.exit_code != 0
        payload = json.loads(result.output)
        assert payload["schema_version"] == "1.1"
        assert payload["ok"] is False
        assert payload["error"] in {"invalid_value", "invalid_option"}
