"""Operation wrappers for image compression workflows."""

from ..compress_engine import CompressResult, collect_compressible_files, compress_single


def collect_files(input_paths: list[str], input_format: str | None, recursive: bool) -> list[str]:
    """Collect candidate files for compression."""
    return collect_compressible_files(input_paths, input_format, recursive)


def compress_one(
    input_path: str,
    output_path: str,
    quality: int | None,
    preset: str,
    target_size: str | None,
    max_size: int | None,
    overwrite: bool,
) -> CompressResult:
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
