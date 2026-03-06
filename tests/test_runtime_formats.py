"""Tests for runtime format capability helpers."""

from pixshift.commands import system_commands
from pixshift.converter import SUPPORTED_INPUT_FORMATS, SUPPORTED_OUTPUT_FORMATS


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

