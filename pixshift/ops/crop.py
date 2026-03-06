"""Operation wrappers for crop workflows."""

from typing import List

from ..crop_engine import collect_croppable_files, crop_single


def collect_files(input_paths: List[str], recursive: bool) -> List[str]:
    """Collect candidate files for crop operations."""
    return collect_croppable_files(input_paths, recursive)


def crop_one(
    input_path: str,
    output_path: str,
    crop_box,
    aspect,
    trim: bool,
    trim_fuzz: int,
    gravity: str,
    overwrite: bool,
):
    """Crop one image with selected strategy."""
    return crop_single(
        input_path=input_path,
        output_path=output_path,
        crop_box=crop_box,
        aspect=aspect,
        trim=trim,
        trim_fuzz=trim_fuzz,
        gravity=gravity,
        overwrite=overwrite,
    )

