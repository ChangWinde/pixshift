"""Operation wrappers for image compare workflows."""

from ..compare_engine import compare_images


def compare(image_a: str, image_b: str, use_blocks: bool = True, block_size: int = 64):
    """Compare two images and return quality metrics."""
    return compare_images(image_a=image_a, image_b=image_b, use_blocks=use_blocks, block_size=block_size)

