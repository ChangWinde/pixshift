"""Geometric transform engine: rotate and flip still images."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from PIL import Image

from .core.errors import OperationPolicyError
from .core.files import atomic_output_path
from .core.metadata import (
    ensure_static_image,
    normalize_orientation,
    normalized_exif_bytes,
    open_image,
)

_ROTATE_TRANSPOSE = {
    90: Image.Transpose.ROTATE_270,
    180: Image.Transpose.ROTATE_180,
    270: Image.Transpose.ROTATE_90,
}
_FLIP_TRANSPOSE = {
    "horizontal": Image.Transpose.FLIP_LEFT_RIGHT,
    "vertical": Image.Transpose.FLIP_TOP_BOTTOM,
}
_SAVE_FORMATS = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
    ".tif": "TIFF",
    ".tiff": "TIFF",
    ".bmp": "BMP",
    ".gif": "GIF",
    ".avif": "AVIF",
    ".heic": "HEIF",
    ".heif": "HEIF",
}


@dataclass
class TransformResult:
    """Result of one rotate/flip operation."""

    input_path: str = ""
    output_path: str = ""
    success: bool = False
    input_size: int = 0
    output_size: int = 0
    duration: float = 0.0
    error: str = ""


def rotate_image(
    input_path: str,
    output_path: str,
    *,
    degrees: int = 0,
    flip: str | None = None,
    overwrite: bool = False,
) -> TransformResult:
    """Rotate clockwise by 90/180/270 degrees and/or mirror a still image.

    EXIF orientation is normalized before the transform so the visual result
    matches what viewers display, and the consumed Orientation tag is removed.
    """
    result = TransformResult(input_path=input_path, output_path=output_path)
    start_time = time.time()
    try:
        if degrees not in (0, 90, 180, 270):
            raise ValueError("degrees_must_be_90_180_or_270")
        if flip is not None and flip not in _FLIP_TRANSPOSE:
            raise ValueError("flip_must_be_horizontal_or_vertical")
        if degrees == 0 and flip is None:
            raise ValueError("nothing_to_do")
        if os.path.exists(output_path) and not overwrite:
            result.error = "output_exists"
            return result

        result.input_size = os.path.getsize(input_path)
        extension = os.path.splitext(output_path)[1].lower()
        save_format = _SAVE_FORMATS.get(extension)
        if save_format is None:
            raise ValueError(f"unsupported_output_format:{extension}")

        with open_image(input_path) as img:
            ensure_static_image(img)
            frame: Image.Image = normalize_orientation(img)
            if degrees:
                frame = frame.transpose(_ROTATE_TRANSPOSE[degrees])
            if flip is not None:
                frame = frame.transpose(_FLIP_TRANSPOSE[flip])

            save_kwargs: dict[str, object] = {}
            exif_bytes = normalized_exif_bytes(frame)
            if exif_bytes:
                save_kwargs["exif"] = exif_bytes
            icc_profile = frame.info.get("icc_profile")
            if icc_profile:
                save_kwargs["icc_profile"] = icc_profile
            if save_format == "JPEG":
                if frame.mode not in ("RGB", "L"):
                    frame = frame.convert("RGB")
                save_kwargs.update({"quality": 95, "subsampling": 0, "optimize": True})
            elif save_format == "WEBP":
                save_kwargs.update({"quality": 95, "method": 4})

            with atomic_output_path(output_path) as temporary:
                frame.save(temporary, format=save_format, **save_kwargs)

        result.output_size = os.path.getsize(output_path)
        result.success = True
    except OperationPolicyError as error:
        result.error = error.code
    except Exception as error:
        result.error = str(error)
    result.duration = time.time() - start_time
    return result
