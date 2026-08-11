"""Operation wrappers for geometric transform workflows."""

from typing import Any

from ..converter import ConvertResult, PixShiftConverter
from ..transform_engine import TransformResult, rotate_image


def resize_one(
    input_path: str,
    output_path: str,
    converter_kwargs: dict[str, Any],
) -> ConvertResult:
    """Resize one file, keeping its format (same-format re-encode)."""
    converter = PixShiftConverter(**converter_kwargs)
    return converter.convert_single(input_path, output_path)


def rotate_one(
    input_path: str,
    output_path: str,
    *,
    degrees: int,
    flip: str | None,
    overwrite: bool,
) -> TransformResult:
    """Rotate or flip one file."""
    return rotate_image(
        input_path,
        output_path,
        degrees=degrees,
        flip=flip,
        overwrite=overwrite,
    )
