"""Operation wrappers for watermark workflows."""

from typing import List, Optional

from ..watermark_engine import add_image_watermark, add_text_watermark, collect_watermark_files


def collect_files(input_paths: List[str], recursive: bool) -> List[str]:
    """Collect candidate files for watermark operations."""
    return collect_watermark_files(input_paths, recursive)


def text_one(
    input_path: str,
    output_path: str,
    text: str,
    font_path: Optional[str],
    font_size: int,
    color: str,
    opacity: int,
    position: str,
    rotation: int,
    tile: bool,
    tile_spacing: int,
    margin: int,
    overwrite: bool,
):
    """Apply text watermark to one image."""
    return add_text_watermark(
        input_path=input_path,
        output_path=output_path,
        text=text,
        font_path=font_path,
        font_size=font_size,
        color=color,
        opacity=opacity,
        position=position,
        rotation=rotation,
        tile=tile,
        tile_spacing=tile_spacing,
        margin=margin,
        overwrite=overwrite,
    )


def image_one(
    input_path: str,
    output_path: str,
    watermark_path: str,
    scale: float,
    opacity: int,
    position: str,
    margin: int,
    tile: bool,
    tile_spacing: int,
    overwrite: bool,
):
    """Apply image watermark to one image."""
    return add_image_watermark(
        input_path=input_path,
        output_path=output_path,
        watermark_path=watermark_path,
        scale=scale,
        opacity=opacity,
        position=position,
        margin=margin,
        tile=tile,
        tile_spacing=tile_spacing,
        overwrite=overwrite,
    )

