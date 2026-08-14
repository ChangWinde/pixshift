"""Operation wrappers for crop workflows."""

from ..core.files import SelectionFilters
from ..crop_engine import CropResult, collect_croppable_files, crop_single


def collect_files(
    input_paths: list[str], recursive: bool, selection: SelectionFilters | None = None
) -> list[str]:
    """Collect candidate files for crop operations."""
    return collect_croppable_files(input_paths, recursive, selection)


def crop_one(
    input_path: str,
    output_path: str,
    crop_box: str | None,
    aspect: str | None,
    trim: bool,
    trim_fuzz: int,
    gravity: str,
    overwrite: bool,
) -> CropResult:
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
