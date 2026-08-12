"""Product-level regressions for common defaults and repeatable workflows."""

import json
from pathlib import Path
from typing import Any

import fitz
import pytest
from click.testing import CliRunner
from PIL import Image

from pixshift.cli import cli
from pixshift.compress_engine import compress_single
from pixshift.converter import PixShiftConverter
from pixshift.core.files import filter_generated_inputs
from pixshift.optimize_engine import _detect_image_type, analyze_image
from pixshift.pdf_engine import (
    _parse_page_range,
    pdf_compress,
    pdf_concat,
    pdf_extract_pages,
    pdf_merge_images,
)
from pixshift.watermark_engine import resolve_font_size


def test_convert_defaults_to_high_quality(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (16, 16), "red").save(source)

    result = CliRunner().invoke(cli, ["convert", str(source), "--to", "jpg", "--dry-run", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["quality"] == "high"
    assert PixShiftConverter().quality == "high"


def test_lossless_formats_ignore_lossy_quality_with_warning(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.png"
    Image.new("RGB", (32, 32), "red").save(source)

    engine_result = compress_single(str(source), str(output), quality=1, overwrite=True)

    assert engine_result.success is True, engine_result.error
    assert engine_result.quality_used == 9

    cli_result = CliRunner().invoke(
        cli,
        [
            "compress",
            str(source),
            "--quality",
            "1",
            "--output",
            str(tmp_path / "compressed"),
            "--json",
        ],
    )
    assert cli_result.exit_code == 0, cli_result.output
    warnings = json.loads(cli_result.output)["warnings"]
    assert warnings == [{"code": "quality_ignored_for_lossless", "files": 1, "formats": ["png"]}]


def test_compress_engine_rejects_unknown_preset(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    Image.new("RGB", (16, 16), "red").save(source)

    result = compress_single(str(source), str(tmp_path / "output.jpg"), preset="mystery")

    assert result.success is False
    assert result.error == "unsupported_compress_preset:mystery"


def test_directory_convert_ignores_existing_target_format(tmp_path: Path) -> None:
    Image.new("RGB", (16, 16), "red").save(tmp_path / "source.png")
    Image.new("RGB", (16, 16), "blue").save(tmp_path / "already.webp")

    result = CliRunner().invoke(
        cli, ["convert", str(tmp_path), "--to", "webp", "--dry-run", "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["total"] == 1
    assert payload["ignored_generated"] == 1
    assert payload["preview"][0]["input"].endswith("source.png")


def test_directory_compress_ignores_prior_derivative(tmp_path: Path) -> None:
    Image.new("RGB", (16, 16), "red").save(tmp_path / "source.jpg")
    Image.new("RGB", (16, 16), "blue").save(tmp_path / "source_compressed.jpg")

    result = CliRunner().invoke(cli, ["compress", str(tmp_path), "--dry-run", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["total"] == 1
    assert payload["ignored_generated"] == 1


@pytest.mark.parametrize(
    ("command", "output_name"),
    [
        (["convert", "--to", "jpg"], "source.jpg"),
        (["compress"], "source_compressed.png"),
        (["strip"], "source_clean.png"),
        (["crop", "--aspect", "1:1"], "source_crop.png"),
        (["watermark", "text", "--text", "demo"], "source_wm.png"),
    ],
)
def test_batch_commands_are_idempotent_when_outputs_exist(
    tmp_path: Path,
    command: list[str],
    output_name: str,
) -> None:
    case_dir = tmp_path / command[0] / (command[1] if command[0] == "watermark" else "case")
    case_dir.mkdir(parents=True)
    source = case_dir / "source.png"
    output = case_dir / "output"
    Image.new("RGB", (24, 16), "red").save(source)
    argv = [*command[:1]]
    if command[0] == "watermark":
        argv.extend(command[1:2])
        argv.append(str(source))
        argv.extend(command[2:])
    else:
        argv.append(str(source))
        argv.extend(command[1:])
    argv.extend(["--output", str(output), "--json"])
    runner = CliRunner()

    first = runner.invoke(cli, argv)
    second = runner.invoke(cli, argv)

    assert first.exit_code == 0, first.output
    assert (output / output_name).is_file()
    assert second.exit_code == 0, second.output
    payload = json.loads(second.output)
    assert payload["ok"] is True
    assert payload["success"] == 0
    assert payload["failed"] == 0
    assert payload["skipped"] == 1


def test_generated_input_filter_excludes_nested_output_but_keeps_explicit_file(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    generated = tmp_path / "out" / "generated.png"
    generated.parent.mkdir()
    source.write_bytes(b"source")
    generated.write_bytes(b"generated")

    discovered, ignored = filter_generated_inputs(
        [str(source), str(generated)],
        [str(tmp_path)],
        output_root=str(generated.parent),
    )
    explicit, explicit_ignored = filter_generated_inputs(
        [str(generated)],
        [str(generated)],
        output_root=str(generated.parent),
    )

    assert discovered == [str(source)]
    assert ignored == 1
    assert explicit == [str(generated)]
    assert explicit_ignored == 0


def test_generated_suffix_without_source_pair_is_not_silently_ignored(tmp_path: Path) -> None:
    legitimate = tmp_path / "archive_compressed.jpg"
    legitimate.write_bytes(b"legitimate")

    retained, ignored = filter_generated_inputs(
        [str(legitimate)],
        [str(tmp_path)],
        generated_suffix="_compressed",
    )

    assert retained == [str(legitimate)]
    assert ignored == 0


def test_watermark_directory_excludes_watermark_asset(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    logo = tmp_path / "logo.png"
    Image.new("RGB", (64, 64), "blue").save(source)
    Image.new("RGBA", (8, 8), (255, 255, 255, 128)).save(logo)

    result = CliRunner().invoke(
        cli,
        [
            "watermark",
            "image",
            str(tmp_path),
            "--watermark",
            str(logo),
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["total"] == 1
    assert payload["ignored_generated"] == 1
    assert payload["preview"][0]["input"].endswith("source.png")


def test_text_watermark_default_font_size_is_adaptive() -> None:
    assert resolve_font_size(None, (100, 100)) == 12
    assert resolve_font_size(None, (1920, 1080)) == 43
    assert resolve_font_size(None, (3840, 2160)) == 86
    assert resolve_font_size(36, (3840, 2160)) == 36


def test_optimize_samples_large_images_and_keeps_high_entropy_photo_classification(
    tmp_path: Path,
) -> None:
    source = tmp_path / "large.png"
    Image.new("RGB", (2000, 1000), "red").save(source)

    result = analyze_image(str(source))
    noisy = Image.effect_noise((1600, 1200), 80).convert("RGB")
    image_type, reason = _detect_image_type(noisy)

    assert result.sampled is True
    assert result.analysis_size == (1600, 800)
    assert image_type == "photo"
    assert "图像熵" in reason


@pytest.mark.parametrize("value", ["", "0", "3", "2-1", "1-3", "one"])
def test_pdf_page_range_rejects_invalid_or_out_of_bounds(value: str) -> None:
    with pytest.raises(ValueError, match="invalid_page_range"):
        _parse_page_range(value, total=2)


def test_pdf_merge_rejects_margin_that_consumes_page(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.pdf"
    Image.new("RGB", (16, 16), "red").save(source)

    result = pdf_merge_images([str(source)], str(output), page_size="a5", margin=300)

    assert result.success is False
    assert result.error == "margin_too_large_for_page"
    assert not output.exists()


@pytest.mark.parametrize(
    ("kwargs", "expected_error"),
    [
        ({"page_size": "poster"}, "unsupported_page_size:poster"),
        ({"quality": 0}, "quality_must_be_between_1_and_100"),
    ],
)
def test_pdf_merge_engine_rejects_invalid_options(
    tmp_path: Path,
    kwargs: dict[str, Any],
    expected_error: str,
) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (16, 16), "red").save(source)

    result = pdf_merge_images([str(source)], str(tmp_path / "output.pdf"), **kwargs)

    assert result.success is False
    assert result.error == expected_error


@pytest.mark.parametrize(
    ("operation", "expected_error"),
    [
        ("extract_format", "unsupported_output_format:bmp"),
        ("extract_dpi", "dpi_must_be_between_72_and_1200"),
        ("compress_preset", "unsupported_pdf_compress_preset:mystery"),
        ("compress_quality", "image_quality_must_be_between_1_and_100"),
        ("compress_dpi", "max_image_dpi_must_be_between_72_and_1200"),
        ("concat", "need_at_least_two"),
    ],
)
def test_pdf_engines_reject_invalid_direct_api_options(
    tmp_path: Path,
    operation: str,
    expected_error: str,
) -> None:
    source = tmp_path / "source.pdf"
    document = fitz.open()
    document.new_page(width=72, height=72)
    document.save(source)
    document.close()
    output = tmp_path / "output.pdf"

    if operation == "extract_format":
        result = pdf_extract_pages(str(source), str(tmp_path / "pages"), output_format="bmp")
    elif operation == "extract_dpi":
        result = pdf_extract_pages(str(source), str(tmp_path / "pages"), dpi=71)
    elif operation == "compress_preset":
        result = pdf_compress(str(source), str(output), preset="mystery")
    elif operation == "compress_quality":
        result = pdf_compress(str(source), str(output), image_quality=0)
    elif operation == "compress_dpi":
        result = pdf_compress(str(source), str(output), max_image_dpi=50)
    else:
        result = pdf_concat([str(source)], str(output))

    assert result.success is False
    assert result.error == expected_error
    assert not output.exists()


def test_pdf_extract_default_is_150_dpi(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "pages"
    document = fitz.open()
    document.new_page(width=72, height=72)
    document.save(source)
    document.close()

    result = CliRunner().invoke(
        cli, ["pdf", "extract", str(source), "--output", str(output), "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dpi"] == 150
    with Image.open(output / "page_0001.png") as image:
        assert image.size == (150, 150)
