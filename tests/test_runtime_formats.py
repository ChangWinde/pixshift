"""Tests for runtime format capability helpers."""

from pathlib import Path

import fitz
from PIL import Image

from pixshift.commands import system_commands
from pixshift.converter import (
    SUPPORTED_INPUT_FORMATS,
    SUPPORTED_OUTPUT_FORMATS,
    PixShiftConverter,
    _build_supported_output_formats,
)


def test_supported_formats_are_runtime_sets():
    assert isinstance(SUPPORTED_INPUT_FORMATS, set)
    assert isinstance(SUPPORTED_OUTPUT_FORMATS, set)
    assert ".jpg" in SUPPORTED_INPUT_FORMATS
    assert "jpg" in SUPPORTED_OUTPUT_FORMATS


def test_preview_items_truncates_long_lists():
    data = [f"v{i}" for i in range(25)]
    text = system_commands._preview_items(data, limit=5)
    assert text.startswith("v0, v1, v2, v3, v4")
    assert "(+" in text


def test_output_capability_probe_treats_runtime_encoder_failure_as_unavailable(monkeypatch):
    monkeypatch.setattr(
        "pixshift.converter.Image.Image.save",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("codec unavailable")),
    )

    assert _build_supported_output_formats() == set()


def test_all_reported_output_formats_complete_a_real_conversion(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGBA", (64, 48), (20, 100, 180, 128)).save(source)
    converter = PixShiftConverter(overwrite=True)

    for output_format in sorted(SUPPORTED_OUTPUT_FORMATS):
        output = tmp_path / f"output.{output_format}"
        result = converter.convert_single(str(source), str(output))

        assert result.success is True, f"{output_format}: {result.error}"
        if output_format == "pdf":
            with fitz.open(output) as document:
                assert document.page_count == 1
        else:
            with Image.open(output) as image:
                image.load()
                assert image.width > 0 and image.height > 0
