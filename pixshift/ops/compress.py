"""Operation wrappers for image compression workflows."""

from typing import List, Optional

from ..compress_engine import collect_compressible_files, compress_single


def collect_files(input_paths: List[str], input_format: Optional[str], recursive: bool) -> List[str]:
    """Collect candidate files for compression."""
    return collect_compressible_files(input_paths, input_format, recursive)


def compress_one(
    input_path: str,
    output_path: str,
    quality: Optional[int],
    preset: str,
    target_size: Optional[str],
    max_size: Optional[int],
    overwrite: bool,
):
    """Compress one file with provided parameters."""
    return compress_single(
        input_path=input_path,
        output_path=output_path,
        quality=quality,
        preset=preset,
        target_size=target_size,
        max_size=max_size,
        overwrite=overwrite,
    )

