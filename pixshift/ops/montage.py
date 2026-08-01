"""Operation wrappers for montage workflows."""

from ..montage_engine import MontageResult, collect_montage_files, create_montage


def collect_files(input_paths: list[str], recursive: bool) -> list[str]:
    """Collect candidate files for montage input."""
    return collect_montage_files(input_paths, recursive)


def create(
    input_paths: list[str],
    output_path: str,
    cols: int,
    gap: int,
    cell_width: int | None,
    cell_height: int | None,
    background: str,
    border: int,
    border_color: str,
    label: bool,
    label_size: int,
    auto_size: bool,
    overwrite: bool,
) -> MontageResult:
    """Create one montage image from input files."""
    return create_montage(
        input_paths=input_paths,
        output_path=output_path,
        cols=cols,
        gap=gap,
        cell_width=cell_width,
        cell_height=cell_height,
        background=background,
        border=border,
        border_color=border_color,
        label=label,
        label_size=label_size,
        auto_size=auto_size,
        overwrite=overwrite,
    )
