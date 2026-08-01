"""Operation wrappers for metadata stripping workflows."""

from typing import Any

from ..strip_engine import StripResult, analyze_metadata, collect_strippable_files, strip_metadata


def collect_files(input_paths: list[str], recursive: bool) -> list[str]:
    """Collect candidate files for metadata stripping."""
    return collect_strippable_files(input_paths, recursive)


def analyze_one(file_path: str) -> dict[str, Any]:
    """Analyze metadata of a single file."""
    return analyze_metadata(file_path)


def strip_one(
    input_path: str,
    output_path: str,
    strip_exif: bool,
    strip_gps: bool,
    strip_icc: bool,
    strip_device: bool,
    strip_personal: bool,
    strip_time: bool,
    keep_orientation: bool,
    overwrite: bool,
) -> StripResult:
    """Strip metadata from one file with selected policy."""
    return strip_metadata(
        input_path=input_path,
        output_path=output_path,
        strip_exif=strip_exif,
        strip_gps=strip_gps,
        strip_icc=strip_icc,
        strip_device=strip_device,
        strip_personal=strip_personal,
        strip_time=strip_time,
        keep_orientation=keep_orientation,
        overwrite=overwrite,
    )
